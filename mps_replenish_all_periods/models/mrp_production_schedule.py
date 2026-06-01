# -*- coding: utf-8 -*-
# =============================================================================
# models/mrp_production_schedule.py
#
# PURPOSE
# -------
# Extend mrp.production.schedule to replenish ALL visible forecast periods
# when the user presses "Order Once" / "Replenish" in the MPS screen.
#
# RFQ INTEGRATION
# ---------------
# All procurements produce Request for Quotation (purchase.order in state
# 'draft') records instead of confirmed POs or Purchase Requisitions.
#
# ROUTING LOGIC
# -------------
#   BUY ROUTE (product has Buy route / no Manufacture route):
#       → Create an RFQ directly for the finished good.
#         Vendor is resolved from product.seller_ids.
#         RFQ date_order = period date_start − (vendor lead time + security lead).
#
#   MANUFACTURE ROUTE (product has Manufacture route on schedule, product,
#     or product category):
#       → Explode the Bill of Materials.
#         For each BOM component that does NOT have its own MPS schedule:
#           • Resolve vendor from component.seller_ids.
#           • Compute order date = date_start − component lead time.
#           • Create / append to an RFQ grouped by vendor.
#         No draft MO is created here; the planner creates MOs manually.
#
# LEAD TIME CALCULATION
# ---------------------
# For each product the "order date" (date_order on the RFQ) is:
#
#   order_date = date_needed
#              − vendor_lead_time   (seller_ids[0].delay, or product.purchase_delay)
#              − security_lead      (company.po_lead)
#              − days_to_purchase   (product.days_to_purchase, if set)
#
# If the computed order_date is in the past, today's date is used instead.
# date_planned on each order line is always the original date_needed.
#
# STOCK COVERAGE
# --------------
# On-hand stock and confirmed incoming PO quantities are deducted before
# creating RFQ lines.  A running balance is maintained across periods
# (earliest first) so on-hand is never double-counted.
# Open Manufacturing Orders are also considered for buy-route FG products.
#
# SURPLUS CARRY-FORWARD
# ---------------------
# When MOQ rounding causes an order to exceed the period's net need, the
# surplus is carried into the next period's available balance so subsequent
# periods do not over-order.  Safety stock protection ensures the safety
# buffer is not consumed by the carry-forward.
#
# RFQ GROUPING
# ------------
# Lines are grouped by (vendor, company, warehouse, year, month).
# One RFQ per group; multiple lines inside one RFQ if the same vendor
# supplies multiple products / components in the same period.
# Lines for the SAME product + date_planned within a group are MERGED
# (quantities summed) so each product appears only once per RFQ.
#
# DUPLICATE DETECTION
# -------------------
# An existing draft/sent RFQ line for the same product + quantity in the
# same year-month raises a UserError listing all conflicts so the planner
# can review before re-running.
#
# BUGS FIXED (carried over from previous version)
# ------------------------------------------------
# BUG 1  — replenish_trigger='never' silently dropped the whole schedule
# BUG 2  — replenish_qty read from stored records (always returns 0)
# BUG 3  — date key type mismatch (ISO string vs Python date object)
# BUG 4  — on-hand stock and confirmed POs not deducted before ordering
# BUG 5  — open MOs not included in available supply for FG coverage
# BUG 6  — surplus from MOQ rounding not carried to next month
# BUG 7  — surplus carry consumed safety stock (protected inventory)
# BUG 8  — component on-hand/PO coverage applied AFTER surplus carry pass
# BUG 9  — BOM explosion triggered for ALL products with a normal BOM
# BUG 10 — same component from multiple BOM paths created duplicate RFQ lines
#           instead of being merged into a single line (quantities now summed)
# =============================================================================

import logging
import math
import calendar
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MrpProductionScheduleAllPeriods(models.Model):
    _inherit = 'mrp.production.schedule'

    # =========================================================================
    # Override: get_production_schedule_view_state
    # Fix on-hand always showing 0 after a completed MO
    # =========================================================================

    def get_production_schedule_view_state(self, period_scale=None):
        """
        Override to replace MPS's context-scoped qty_available with a direct
        stock.quant read at warehouse.lot_stock_id (including child locations).
        """
        if period_scale is not None:
            result = super().get_production_schedule_view_state(period_scale)
        else:
            result = super().get_production_schedule_view_state()

        schedule_by_id = {rec.id: rec for rec in self}

        for mps_state in result:
            schedule = schedule_by_id.get(mps_state.get('id'))
            if not schedule:
                continue

            product   = schedule.product_id
            company   = schedule.company_id
            warehouse = schedule.warehouse_id
            location  = warehouse.lot_stock_id if warehouse else False

            if location:
                quants = self.env['stock.quant'].search([
                    ('product_id',  '=', product.id),
                    ('location_id', 'child_of', location.id),
                    ('company_id',  '=', company.id),
                ])
                real_on_hand = sum(
                    max(0.0, q.quantity - q.reserved_quantity) for q in quants
                )
            else:
                real_on_hand = product.with_context(
                    force_company=company.id
                ).qty_available

            odoo_on_hand = mps_state.get('qty_on_hand', 0.0) or 0.0

            if abs(real_on_hand - odoo_on_hand) > 0.001:
                _logger.info(
                    "[MPS Display Fix] %s: Odoo on_hand=%.4f → corrected to %.4f "
                    "(direct stock.quant @ %s + children)",
                    product.display_name, odoo_on_hand, real_on_hand,
                    location.complete_name if location else 'N/A',
                )

            mps_state['qty_on_hand'] = real_on_hand

            forecast_ids = mps_state.get('forecast_ids', [])
            if forecast_ids:
                def _period_sort_key(p):
                    ds = p.get('date_start')
                    if isinstance(ds, str):
                        return date_type.fromisoformat(ds)
                    return ds or date_type.min

                sorted_periods = sorted(forecast_ids, key=_period_sort_key)
                first_period   = sorted_periods[0]

                odoo_fq0 = first_period.get('forecasted_qty_0', 0.0) or 0.0
                if abs(real_on_hand - odoo_fq0) > 0.001:
                    first_period['forecasted_qty_0'] = real_on_hand

                    demand        = first_period.get('forecast_qty',       0.0) or 0.0
                    incoming      = first_period.get('incoming_qty',       0.0) or 0.0
                    target        = first_period.get('forecast_target_qty',0.0) or 0.0
                    old_replenish = first_period.get('replenish_qty',      0.0) or 0.0

                    new_replenish = max(0.0, target - (real_on_hand + incoming - demand))
                    first_period['replenish_qty'] = new_replenish

                    _logger.info(
                        "[MPS Display Fix] %s first period: "
                        "forecasted_qty_0 %.4f→%.4f  replenish_qty %.4f→%.4f",
                        product.display_name,
                        odoo_fq0, real_on_hand, old_replenish, new_replenish,
                    )

        return result

    # =========================================================================
    # Helper: MOQ adjustment (no safety stock applied to BOM components)
    # =========================================================================

    def _mps_adjust_procurement_qty(
        self, product, raw_qty, forecasted_on_hand=0.0, apply_safety=True
    ):
        """Apply safety stock and minimum order quantity rules (FG only)."""
        self.ensure_one()
        tmpl     = product.product_tmpl_id
        adjusted = (
            tmpl._apply_procurement_qty_rules(raw_qty, forecasted_on_hand)
            if apply_safety
            else tmpl._apply_minimum_order_qty(raw_qty)
        )
        if adjusted != raw_qty:
            _logger.info(
                "[MPS All-Periods] qty adjusted for %s: %.4f → %.4f "
                "(safety_stock=%.4f, min_order_qty=%.4f, on_hand=%.4f)",
                product.display_name, raw_qty, adjusted,
                tmpl._get_safety_stock() if apply_safety else 0.0,
                tmpl._get_minimum_order_qty(),
                forecasted_on_hand,
            )
        return adjusted

    # =========================================================================
    # Helper: resolve vendor for a product
    # =========================================================================

    def _mps_get_vendor(self, product, company, quantity=0.0, uom=None):
        """
        Return the best res.partner vendor for ``product``.

        Resolution order:
          1. product._select_seller() — considers quantity breaks and date.
          2. First entry in product.seller_ids filtered by company.
          3. First entry in product.seller_ids (any company).

        Returns a product.supplierinfo record (may be empty recordset if none
        found, in which case the caller should handle gracefully).
        """
        seller = product._select_seller(
            quantity=quantity,
            date=datetime.now().date(),
            uom_id=uom,
        )
        if seller:
            return seller

        # Fallback: first supplierinfo in company, then any
        sellers = product.seller_ids.filtered(
            lambda s: not s.company_id or s.company_id == company
        )
        if sellers:
            return sellers[0]

        if product.seller_ids:
            return product.seller_ids[0]

        return self.env['product.supplierinfo']

    # =========================================================================
    # Helper: compute RFQ order date from period date + product lead time
    # =========================================================================

    def _mps_compute_order_date(self, date_needed, product, company, seller=None):
        """
        Return (order_date, realistic_date_planned) so that goods arrive
        by ``date_needed``.

        If order_date would be in the past, it is clamped to today and
        date_planned is recalculated as today + total_lead so the RFQ
        reflects when the goods will actually arrive.
        """
        if isinstance(date_needed, date_type) and not isinstance(date_needed, datetime):
            base = date_needed
        else:
            base = date_needed.date() if isinstance(date_needed, datetime) else date_type.today()

        vendor_lead = float(seller.delay if seller and seller.delay else 0.0)
        days_to_purchase = float(getattr(product, 'days_to_purchase', 0.0) or 0.0)
        security_lead = float(getattr(company, 'po_lead', 0.0) or 0.0)

        total_lead = vendor_lead + days_to_purchase + security_lead
        order_date = base - timedelta(days=total_lead)

        today = date_type.today()
        was_clamped = order_date < today
        if was_clamped:
            order_date = today

        # If clamped, realistic arrival = today + total_lead, not the original date_needed
        realistic_date_planned = (
            today + timedelta(days=total_lead) if was_clamped else base
        )

        _logger.info(
            "[MPS RFQ] Lead time for %s: vendor=%.0fd  days_to_purchase=%.0fd  "
            "security=%.0fd  total=%.0fd  date_needed=%s → order_date=%s  "
            "date_planned=%s%s",
            product.display_name, vendor_lead, days_to_purchase, security_lead,
            total_lead, base, order_date, realistic_date_planned,
            "  [LATE — clamped]" if was_clamped else "",
        )
        return order_date, realistic_date_planned

    # =========================================================================
    # Helper: build a human-readable origin string
    # =========================================================================

    def _mps_get_replenishment_origin(self, date_start, date_stop=None):
        self.ensure_one()
        product_ref    = self.product_id.default_code or self.product_id.display_name
        warehouse_code = self.warehouse_id.code or 'WH'
        date_str = (
            date_start.strftime('%Y-%m-%d')
            if hasattr(date_start, 'strftime') else str(date_start)
        )
        return f"MPS/{warehouse_code}/{product_ref}/{date_str}"

    # =========================================================================
    # Helper: stock coverage — on-hand qty
    # =========================================================================

    def _mps_get_on_hand_qty(self, product, company, warehouse):
        """Return unreserved on-hand quantity at warehouse.lot_stock_id."""
        location = warehouse.lot_stock_id if warehouse else False
        if location:
            quants  = self.env['stock.quant'].search([
                ('product_id',  '=',  product.id),
                ('location_id', 'child_of', location.id),
                ('company_id',  '=',  company.id),
            ])
            on_hand = sum(max(0.0, q.quantity - q.reserved_quantity) for q in quants)
        else:
            on_hand = product.with_context(force_company=company.id).qty_available

        _logger.info(
            "[MPS Coverage] on_hand for %s @ %s : %.4f",
            product.display_name,
            warehouse.code if warehouse else 'N/A',
            on_hand,
        )
        return on_hand

    # =========================================================================
    # Helper: confirmed PO incoming quantities by (year, month)
    # =========================================================================

    def _mps_get_open_po_qty_by_month(self, product, company, warehouse):
        """Return confirmed-PO incoming quantities keyed by (year, month)."""
        domain = [
            ('product_id',          '=',  product.id),
            ('order_id.state',      'in', ['purchase']),
            ('order_id.company_id', '=',  company.id),
        ]
        if warehouse:
            domain.append(
                ('order_id.picking_type_id.warehouse_id', '=', warehouse.id)
            )

        by_month = {}
        for line in self.env['purchase.order.line'].search(domain):
            remaining = max(0.0, line.product_uom_qty - (line.qty_received or 0.0))
            if remaining <= 0.0:
                continue
            receipt_dt = line.date_planned
            if isinstance(receipt_dt, str):
                receipt_dt = datetime.fromisoformat(receipt_dt)
            if not receipt_dt:
                continue
            key = (receipt_dt.year, receipt_dt.month)
            by_month[key] = by_month.get(key, 0.0) + remaining

        if by_month:
            _logger.info(
                "[MPS Coverage] open PO incoming for %s: %s",
                product.display_name,
                {"%d-%02d" % k: v for k, v in sorted(by_month.items())},
            )
        return by_month

    # =========================================================================
    # Helper: open MO quantities by (year, month)
    # =========================================================================

    def _mps_get_open_mo_qty_by_month(self, product, company, warehouse):
        """Return open MO expected output quantities keyed by (year, month)."""
        if not self.env['ir.model'].search(
            [('model', '=', 'mrp.production')], limit=1
        ):
            return {}

        domain = [
            ('product_id', '=',  product.id),
            ('state',      'in', ['confirmed', 'progress', 'to_close']),
            ('company_id', '=',  company.id),
        ]
        if warehouse:
            domain.append(('picking_type_id.warehouse_id', '=', warehouse.id))

        by_month = {}
        for mo in self.env['mrp.production'].search(domain):
            remaining = max(0.0, (mo.product_qty or 0.0) - (mo.qty_produced or 0.0))
            if remaining <= 0.0:
                continue
            sched_date = (
                mo.date_deadline
                or getattr(mo, 'date_planned_start', None)
                or getattr(mo, 'scheduled_date', None)
            )
            if isinstance(sched_date, str):
                sched_date = datetime.fromisoformat(sched_date)
            if not sched_date:
                continue
            key = (sched_date.year, sched_date.month)
            by_month[key] = by_month.get(key, 0.0) + remaining

        if by_month:
            _logger.info(
                "[MPS Coverage] open MO supply for %s: %s",
                product.display_name,
                {"%d-%02d" % k: v for k, v in sorted(by_month.items())},
            )
        return by_month

    # =========================================================================
    # Helper: detect manufacture route
    # =========================================================================

    def _mps_has_manufacture_route(self, production_schedule):
        """
        Return True if the schedule/product/category declares a Manufacture route.

        Checks three sources in priority order:
          1. production_schedule.route_id  (MPS form "Route" field — most authoritative)
          2. product.route_ids             (Inventory tab on product form)
          3. product.categ_id.route_ids    (product category routes)
        """
        def _is_mfg(route):
            if not route:
                return False
            name = (route.name or '').lower()
            return 'manufactur' in name or 'fabricat' in name

        if _is_mfg(production_schedule.route_id):
            return True

        for r in list(production_schedule.product_id.route_ids) + \
                 list(production_schedule.product_id.categ_id.route_ids):
            if _is_mfg(r):
                return True

        return False

    # =========================================================================
    # Helper: detect manufacture route on a plain product (no schedule context)
    # Used when inspecting BOM components during recursive explosion.
    # =========================================================================

    def _mps_component_has_manufacture_route(self, product):
        """
        Return True if ``product`` or its category carries a Manufacture route.
        Unlike _mps_has_manufacture_route() this does NOT look at a schedule
        record — it is used for BOM components where no MPS schedule exists.
        """
        def _is_mfg(route):
            if not route:
                return False
            name = (route.name or '').lower()
            return 'manufactur' in name or 'fabricat' in name

        for r in list(product.route_ids) + list(product.categ_id.route_ids):
            if _is_mfg(r):
                return True
        return False

    # =========================================================================
    # Helper: duplicate RFQ line detection
    # =========================================================================

    def _mps_find_existing_rfq_line(self, product_id, quantity, year=None, month=None):
        """
        Search for a draft/sent purchase.order.line for the same product + qty,
        optionally scoped to a specific period (year + month) via date_planned.

        Without year/month the check is period-agnostic.
        Returns a recordset of matching purchase.order.line records.
        """
        rfq_states = ['draft', 'sent']
        candidates = self.env['purchase.order.line'].search([
            ('product_id',      '=',  product_id),
            ('order_id.state',  'in', rfq_states),
        ])

        tolerance = 0.001
        matched   = candidates.filtered(
            lambda l, q=quantity, t=tolerance: abs(l.product_uom_qty - q) <= t
        )

        if matched and year is not None and month is not None:
            def _in_period(line, y=year, m=month):
                dp = line.date_planned
                if not dp:
                    return False
                if hasattr(dp, 'year'):
                    return dp.year == y and dp.month == m
                try:
                    d = date_type.fromisoformat(str(dp))
                    return d.year == y and d.month == m
                except Exception:
                    return False
            matched = matched.filtered(_in_period)

        return matched

    # =========================================================================
    # Helper: get or create receipt picking type for warehouse
    # =========================================================================

    def _mps_get_picking_type(self, warehouse, company):
        """Return the incoming picking type for the given warehouse."""
        if warehouse:
            pt = self.env['stock.picking.type'].search([
                ('code',         '=', 'incoming'),
                ('warehouse_id', '=', warehouse.id),
                ('company_id',   '=', company.id),
            ], limit=1)
            if pt:
                return pt
        return self.env['stock.picking.type'].search([
            ('code',       '=', 'incoming'),
            ('company_id', '=', company.id),
        ], limit=1)

    # =========================================================================
    # Core RFQ creation
    # =========================================================================

    def _mps_create_rfqs(self, rfq_lines, origin=None):
        """
        Create RFQ (purchase.order in state='draft') records from a list of
        line specification dicts.

        Each dict in ``rfq_lines`` must have:
            product   (product.product)
            qty       (float)
            uom       (uom.uom)
            company   (res.company)
            warehouse (stock.warehouse | False)
            date_needed (date)   — goes to order_line.date_planned
            year      (int)
            month     (int)

        Lines are grouped by (vendor.id, company.id, warehouse.id, year, month).
        One purchase.order per group is created; multiple lines land in the same
        RFQ when the same vendor supplies several products in the same period.

        Within each group, lines for the SAME (product_id, date_planned) are
        MERGED — their quantities are summed — so each product appears at most
        once per RFQ line.

        Returns a list of purchase.order records created.
        """
        PurchaseOrder  = self.env['purchase.order']
        created_rfqs   = []
        duplicate_info = []

        # ── Duplicate check ───────────────────────────────────────────────────
        filtered_lines = []
        for spec in rfq_lines:
            existing = self._mps_find_existing_rfq_line(
                spec['product'].id, spec['qty'],
                year=spec['year'], month=spec['month'],
            )
            if existing:
                po_names = sorted({l.order_id.name for l in existing if l.order_id.name})
                duplicate_info.append((
                    spec['product'].display_name,
                    spec['qty'],
                    ', '.join(po_names) or '(unnamed)',
                ))
                _logger.info(
                    "[MPS RFQ] DUPLICATE BLOCKED: %s qty=%.3f already in RFQ(s): %s",
                    spec['product'].display_name, spec['qty'],
                    ', '.join(po_names),
                )
            else:
                filtered_lines.append(spec)

        if duplicate_info:
            conflict_lines = "\n".join(
                "  • %s  (qty: %.3f)  →  %s" % (name, qty, rfqs)
                for name, qty, rfqs in duplicate_info
            )
            raise UserError(_(
                "Cannot replenish: the following item(s) already exist in an "
                "open RFQ with the same quantity.\n"
                "Please review or cancel the existing RFQ before replenishing again.\n\n"
                "%s"
            ) % conflict_lines)

        if not filtered_lines:
            _logger.info("[MPS RFQ] All lines already covered by existing RFQs.")
            return []

        # ── Group by (vendor, company, warehouse, year, month) ────────────────
        # Within each group, lines are further keyed by (product_id, date_planned)
        # so that the same product arriving on the same date is merged into a
        # single RFQ line (quantities summed) rather than creating duplicates.
        groups = {}

        for spec in filtered_lines:
            product   = spec['product']
            company   = spec['company']
            warehouse = spec['warehouse']
            year      = spec['year']
            month     = spec['month']

            seller = self._mps_get_vendor(
                product, company,
                quantity=spec['qty'],
                uom=spec.get('uom'),
            )
            # product.supplierinfo.partner_id is the res.partner (vendor).
            partner = seller.partner_id if seller else False

            if not partner:
                _logger.warning(
                    "[MPS RFQ] No vendor found for %s — skipping RFQ line.",
                    product.display_name,
                )
                continue

            order_date, date_planned = self._mps_compute_order_date(
                spec['date_needed'], product, company, seller=seller,
            )

            group_key = (
                partner.id,
                company.id,
                warehouse.id if warehouse else False,
                year,
                month,
            )

            if group_key not in groups:
                groups[group_key] = {
                    'partner':    partner,
                    'company':    company,
                    'warehouse':  warehouse,
                    'year':       year,
                    'month':      month,
                    'order_date': order_date,
                    'lines':      {},   # keyed by (product_id, date_planned_dt)
                }
            else:
                # Use the earliest order_date across all lines in the group
                if order_date < groups[group_key]['order_date']:
                    groups[group_key]['order_date'] = order_date

            # ── Compute date_planned as datetime ─────────────────────────────
            date_needed = spec['date_needed']
            if isinstance(date_planned, date_type) and not isinstance(date_planned, datetime):
                date_planned_dt = datetime.combine(date_planned, datetime.min.time())
            else:
                date_planned_dt = date_planned

            # ── Merge by (product_id, date_planned) within the group ──────────
            line_key = (product.id, date_planned_dt)
            group_lines = groups[group_key]['lines']

            if line_key in group_lines:
                old_qty = group_lines[line_key]['product_qty']
                group_lines[line_key]['product_qty'] += spec['qty']
                _logger.info(
                    "[MPS RFQ] Merged line for %s on %s: %.4f + %.4f = %.4f",
                    product.display_name, date_planned_dt,
                    old_qty, spec['qty'], group_lines[line_key]['product_qty'],
                )
            else:
                group_lines[line_key] = {
                    'product_id':   product.id,
                    'product_uom':  spec['uom'].id if spec.get('uom') else product.uom_po_id.id,
                    'product_qty':  spec['qty'],
                    'price_unit':   seller.price if seller else 0.0,
                    'date_planned': date_planned_dt,
                    'name':         product.display_name,
                }

        # ── Create one RFQ per group ──────────────────────────────────────────
        for group_key, group in groups.items():
            if not group['lines']:
                continue

            picking_type = self._mps_get_picking_type(group['warehouse'], group['company'])
            month_name   = calendar.month_abbr[group['month']]

            # group['lines'] is a dict keyed by (product_id, date_planned_dt);
            # extract the plain line dicts for the ORM.
            orm_lines = list(group['lines'].values())

            po_vals = {
                'partner_id':  group['partner'].id,
                'company_id':  group['company'].id,
                'date_order':  datetime.combine(group['order_date'], datetime.min.time()),
                'origin':      origin or (
                    f"MPS/{group['year']}-{group['month']:02d}"
                ),
                'order_line':  [(0, 0, l) for l in orm_lines],
            }
            if picking_type:
                po_vals['picking_type_id'] = picking_type.id

            rfq = PurchaseOrder.create(po_vals)
            rfq.message_post(
                body=_(
                    'Created automatically by MPS replenishment.  '
                    'Period: <b>%s %s</b>  '
                    'Triggered by: <b>%s</b>'
                ) % (month_name, group['year'], self.env.user.name)
            )

            _logger.info(
                "[MPS RFQ] Created RFQ %s  vendor=%s  period=%d-%02d  "
                "lines=%d  order_date=%s",
                rfq.name, group['partner'].name,
                group['year'], group['month'],
                len(orm_lines), group['order_date'],
            )
            created_rfqs.append(rfq)

        return created_rfqs

    # =========================================================================
    # BOM explosion → RFQ lines (recursive, handles SFG manufacture components)
    # =========================================================================

    def _mps_build_component_rfq_lines_from_bom(
            self,
            product,
            qty,
            uom,
            date_start,
            date_stop,
            company,
            warehouse,
            comp_coverage_state,
    ):
        """
        Entry point: explode the BOM for ``product`` × ``qty`` and return all
        buy-route leaf component RFQ line specs.
        """
        self.ensure_one()
        return self._mps_collect_rfq_lines_recursive(
            product=product,
            qty=qty,
            company=company,
            warehouse=warehouse,
            date_start=date_start,
            date_stop=date_stop,
            comp_coverage_state=comp_coverage_state,
            ancestors=set(),
            depth=0,
        )

    def _mps_collect_rfq_lines_recursive(
            self,
            product,
            qty,
            company,
            warehouse,
            date_start,
            date_stop,  # ← add this
            comp_coverage_state,
            ancestors,
            depth,
    ):
        """
        Recursive BOM explosion used by _mps_build_component_rfq_lines_from_bom.

        For each component in the BOM:
          • Has own MPS schedule          → skip (it replenishes itself)
          • Circular reference / too deep → skip with warning
          • Has Manufacture route          → deduct SFG coverage, then recurse
                                            into the SFG's own BOM
          • Buy-route (leaf)               → apply coverage + MOQ, emit RFQ spec

        Args:
            product            Finished good or SFG whose BOM to explode.
            qty                Quantity required (net, already coverage-adjusted
                               by the caller for non-top-level calls).
            company / warehouse
            date_start         Period start date (determines period_key).
            comp_coverage_state Mutable shared coverage dict.
            ancestors          Set of product IDs on the current call stack
                               (circular reference guard).
            depth              Current recursion depth (safety cap = 8).

        Returns:
            list of RFQ line spec dicts for _mps_create_rfqs().
        """
        MAX_DEPTH  = 8
        period_key = (date_start.year, date_start.month)

        if depth > MAX_DEPTH:
            _logger.warning(
                "[MPS BOM Explode] Max recursion depth (%d) reached for %s "
                "— stopping here.",
                MAX_DEPTH, product.display_name,
            )
            return []

        if product.id in ancestors:
            _logger.warning(
                "[MPS BOM Explode] Circular BOM reference detected: %s "
                "already in ancestor chain %s — skipping.",
                product.display_name, ancestors,
            )
            return []

        # ── 1. Find BOM ───────────────────────────────────────────────────────
        bom = self.env['mrp.bom']._bom_find(
            product,
            company_id=company.id,
            bom_type='normal',
        )[product]

        if not bom:
            if depth > 0:
                _logger.warning(
                    "[MPS BOM Explode] Manufacture-route component %s has no "
                    "BOM and no vendor — cannot determine what to order. "
                    "Add a BOM or a vendor pricelist to this product.",
                    product.display_name,
                )
            else:
                _logger.warning(
                    "[MPS BOM Explode] No normal BOM for top-level product %s.",
                    product.display_name,
                )
            return []

        _dummy, bom_lines = bom.explode(product, qty)
        if not bom_lines:
            _logger.warning(
                "[MPS BOM Explode] BOM explosion for %s returned no lines.",
                product.display_name,
            )
            return []

        # ── 2. Identify components with their own MPS schedules ───────────────
        all_comp_ids = [bl.product_id.id for bl, _ld in bom_lines]
        already_scheduled_ids = set(
            self.env['mrp.production.schedule'].search([
                ('company_id',   '=', company.id),
                ('warehouse_id', '=', warehouse.id),
                ('product_id',   'in', all_comp_ids),
            ]).product_id.ids
        )

        # Build ancestor set for child calls (add current product)
        child_ancestors = ancestors | {product.id}

        rfq_line_specs = []

        for bom_line, line_data in bom_lines:
            comp     = bom_line.product_id
            comp_qty = line_data['qty']   # scaled to the requested qty already

            # ── Guard: circular reference or FG self-reference ────────────────
            if comp.id == product.id or comp.id in ancestors:
                _logger.warning(
                    "[MPS BOM Explode] Circular/self reference: %s in BOM of "
                    "%s — skipped.",
                    comp.display_name, product.display_name,
                )
                continue

            # ── Skip components with own MPS schedule ─────────────────────────
            if comp.id in already_scheduled_ids:
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s → component %s has its "
                    "own MPS schedule — skipped.",
                    depth, product.display_name, comp.display_name,
                )
                continue

            # ── Coverage: initialise on first encounter ───────────────────────
            if comp.id not in comp_coverage_state:
                comp_on_hand     = self._mps_get_on_hand_qty(comp, company, warehouse)
                comp_po_by_month = self._mps_get_open_po_qty_by_month(
                    comp, company, warehouse,
                )
                comp_coverage_state[comp.id] = {
                    'on_hand':                 comp_on_hand,
                    'po_by_month':             comp_po_by_month,
                    'balance':                 comp_on_hand,
                    'safety_stock_considered': False,
                }
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s: initial coverage "
                    "on_hand=%.4f  po_months=%s",
                    depth, comp.display_name, comp_on_hand,
                    list(comp_po_by_month.keys()),
                )

            cov         = comp_coverage_state[comp.id]
            po_arriving = cov['po_by_month'].get(period_key, 0.0)
            cov['balance'] += po_arriving

            net_comp_qty   = max(0.0, comp_qty - cov['balance'])
            cov['balance'] = max(0.0, cov['balance'] - comp_qty)

            _logger.info(
                "[MPS BOM Explode] depth=%d  %-30s  period %d-%02d : "
                "bom_qty=%.4f  po_arriving=%.4f  net_qty=%.4f  "
                "balance_after=%.4f",
                depth, comp.display_name, period_key[0], period_key[1],
                comp_qty, po_arriving, net_comp_qty, cov['balance'],
            )

            if net_comp_qty <= 0.0:
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s period %d-%02d fully "
                    "covered by on-hand / open PO — no RFQ needed.",
                    depth, comp.display_name, period_key[0], period_key[1],
                )
                continue

            # ── Manufacture-route SFG: recurse into its BOM ───────────────────
            if self._mps_component_has_manufacture_route(comp):
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s is a manufacture-route "
                    "SFG (net_qty=%.4f) — recursing into its BOM.",
                    depth, comp.display_name, net_comp_qty,
                )
                sub_specs = self._mps_collect_rfq_lines_recursive(
                    product=comp,
                    qty=net_comp_qty,
                    company=company,
                    warehouse=warehouse,
                    date_start=date_start,
                    date_stop=date_stop,  # ← this was missing
                    comp_coverage_state=comp_coverage_state,
                    ancestors=child_ancestors,
                    depth=depth + 1,
                )
                rfq_line_specs.extend(sub_specs)
                # Do NOT carry surplus for SFGs — surplus is an internal
                # production decision, not a purchase surplus.
                continue

            # ── Buy-route leaf component: apply MOQ + emit RFQ spec ──────────
            # NEW
            # ── Buy-route leaf component: apply safety stock once + MOQ ──
            tmpl = comp.product_tmpl_id

            safety_stock = (
                tmpl._get_safety_stock()
                if (
                    not cov.get('safety_stock_considered')
                    and hasattr(tmpl, '_get_safety_stock')
                ) else 0.0
            )
            cov['safety_stock_considered'] = True

            # Only add safety stock if the current balance won't already cover it
            # (i.e. don't double-count if on-hand already exceeds safety stock)
            safety_top_up = max(0.0, safety_stock - cov['balance'])
            net_with_safety = net_comp_qty + safety_top_up

            if safety_top_up > 0.0:
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s period %d-%02d: "
                    "safety_stock=%.4f  balance_after_period=%.4f  "
                    "top_up=%.4f  net_comp_qty %.4f → %.4f",
                    depth, comp.display_name, period_key[0], period_key[1],
                    safety_stock, cov['balance'], safety_top_up,
                    net_comp_qty, net_with_safety,
                )

            moq = (
                tmpl._get_minimum_order_qty()
                if hasattr(tmpl, '_get_minimum_order_qty') else 0.0
            )
            if moq and moq > 0.0:
                adjusted = math.ceil(net_with_safety / moq) * moq
                if adjusted != net_with_safety:
                    _logger.info(
                        "[MPS BOM Explode] depth=%d  %s MOQ rounding: "
                        "%.4f → %.4f  (moq=%.4f)",
                        depth, comp.display_name,
                        net_with_safety, adjusted, moq,
                    )
            else:
                adjusted = net_with_safety

            # Carry MOQ surplus back into the running balance so the next
            # period does not over-order for the same buy-route component.
            surplus = adjusted - net_with_safety
            if (
                    surplus > 0.0):
                cov['balance'] += surplus
                _logger.info(
                    "[MPS BOM Explode] depth=%d  %s period %d-%02d: "
                    "MOQ surplus %.4f carried forward → balance=%.4f",
                    depth, comp.display_name, period_key[0], period_key[1],
                    surplus, cov['balance'],
                )

            rfq_line_specs.append({
                'product': comp,
                'qty': adjusted,
                'uom': bom_line.product_uom_id,
                'company': company,
                'warehouse': warehouse,
                'date_needed': date_type(period_key[0], period_key[1], 1),
                'year': period_key[0],
                'month': period_key[1],
            })

        return rfq_line_specs

    # =========================================================================
    # Main override: action_replenish
    # =========================================================================

    def action_replenish(self, based_on_lead_time=False):
        """
        Override action_replenish() to process ALL visible forecast periods
        and route every procurement to an RFQ (purchase.order, state='draft').

        ROUTING PER PRODUCT
        -------------------
        MANUFACTURE ROUTE  (schedule.route_id, product.route_ids, or
                            product.categ_id.route_ids contains Manufacture):
            → The product's BOM is exploded.
            → An RFQ is created for each component whose net need > 0.
            → Component RFQ order_date = date_start − component lead time.
            → No Manufacturing Order is created; the planner creates MOs
              manually after reviewing the replenishment.

        BUY ROUTE (all other products):
            → An RFQ is created directly for the finished good.
            → RFQ order_date = date_start − product lead time.

        TRIGGER='never' (regardless of route):
            → Same as manufacture route above: BOM exploded, component RFQs
              created, no MO.  This is the "manual MO" workflow where the
              planner wants raw materials purchased but controls MO creation.

        STOCK COVERAGE
            On-hand + confirmed incoming PO + open MO quantities are deducted
            before ordering.  Running balance maintained across periods.

        SURPLUS CARRY-FORWARD
            MOQ rounding surplus is carried into the next period's balance to
            avoid cumulative over-ordering.

        DUPLICATE DETECTION
            Existing draft/sent RFQs for the same product + qty + period raise
            a UserError so the planner can review before re-running.

        LINE MERGING
            Within each RFQ (grouped by vendor/company/warehouse/period),
            multiple specs for the same product + date_planned are merged into
            a single order line (quantities summed).
        """
        _logger.info(
            "[MPS All-Periods] action_replenish called | schedules=%s | "
            "lead_time=%s",
            self.ids, based_on_lead_time,
        )

        production_schedules = self
        if not production_schedules:
            _logger.info("[MPS All-Periods] No schedules selected. Returning.")
            return False

        production_schedule_states = production_schedules.get_production_schedule_view_state()
        state_by_id = {mps['id']: mps for mps in production_schedule_states}

        # Accumulator for buy-route finished goods (PATH D) and phantom BOMs
        # (PATH C).  Manufacture-route products (PATH A) and trigger='never'
        # with a BOM (PATH B) are handled inline and emit rfq_line_specs directly.
        raw_qty_accumulator = {}

        # Per-schedule component coverage state shared across periods.
        # { schedule_id: { comp_product_id: {'on_hand', 'po_by_month', 'balance'} } }
        schedule_comp_coverage = {}

        # All RFQ line specs collected from PATH A and PATH B
        all_rfq_line_specs = []

        # Forecast records to mark as procurement_launched
        forecasts_to_set_as_launched = self.env['mrp.product.forecast']
        forecasts_values             = []
        # deferred tracking: (schedule.id, year, month) → (sched, ds, de, existing)
        acc_key_to_forecast_records  = {}

        # ── Per-schedule processing ───────────────────────────────────────────
        for production_schedule in production_schedules:
            schedule_state = state_by_id.get(production_schedule.id)
            if not schedule_state:
                continue

            is_never      = production_schedule.replenish_trigger == 'never'
            has_mfg_route = self._mps_has_manufacture_route(production_schedule)

            _logger.info(
                "[MPS All-Periods] Schedule %s (%s): "
                "trigger=%s  has_mfg_route=%s",
                production_schedule.product_id.display_name,
                production_schedule.id,
                production_schedule.replenish_trigger,
                has_mfg_route,
            )

            # ── Determine routing path ────────────────────────────────────────
            #
            # PATH A — Manufacture route AND trigger != 'never'
            #   → Explode BOM → component RFQs (handled inline per period)
            #
            # PATH B — trigger='never' (any route, as long as a normal BOM exists)
            #   → Explode BOM → component RFQs (same as A, just no MO created)
            #   → If no BOM found, falls through to PATH D (buy the FG directly)
            #
            # PATH C — Phantom / kit BOM, no manufacture route
            #   → Explode phantom BOM → component RFQs via accumulator
            #
            # PATH D — Standard buy-route FG (no manufacture route, no phantom)
            #   → RFQ for the FG itself via accumulator

            use_bom_explosion = False    # True for PATH A and PATH B
            bom_for_explosion = None

            if has_mfg_route and not is_never:
                # PATH A
                bom_for_explosion = self.env['mrp.bom']._bom_find(
                    production_schedule.product_id,
                    company_id=production_schedule.company_id.id,
                    bom_type='normal',
                )[production_schedule.product_id]

                if bom_for_explosion:
                    use_bom_explosion = True
                    _logger.info(
                        "[MPS All-Periods] PATH A — %s: Manufacture route. "
                        "BOM will be exploded; component RFQs will be created.",
                        production_schedule.product_id.display_name,
                    )
                else:
                    _logger.warning(
                        "[MPS All-Periods] %s has Manufacture route but no "
                        "normal BOM — falling back to PATH D (RFQ for FG).",
                        production_schedule.product_id.display_name,
                    )

            elif is_never:
                # PATH B
                bom_for_explosion = self.env['mrp.bom']._bom_find(
                    production_schedule.product_id,
                    company_id=production_schedule.company_id.id,
                    bom_type='normal',
                )[production_schedule.product_id]

                if bom_for_explosion:
                    use_bom_explosion = True
                    _logger.info(
                        "[MPS All-Periods] PATH B — %s: trigger='never'. "
                        "BOM exploded; component RFQs only, no MO.",
                        production_schedule.product_id.display_name,
                    )
                else:
                    _logger.info(
                        "[MPS All-Periods] PATH B — %s: trigger='never' but "
                        "no normal BOM — falling back to PATH D.",
                        production_schedule.product_id.display_name,
                    )

            # ── Phantom BOM (PATH C) ──────────────────────────────────────────
            phantom_bom           = None
            phantom_product_ratio = []

            if not use_bom_explosion:
                phantom_bom = self.env['mrp.bom']._bom_find(
                    production_schedule.product_id,
                    company_id=production_schedule.company_id.id,
                    bom_type='phantom',
                )[production_schedule.product_id]

                if phantom_bom:
                    _dummy, bom_lines = phantom_bom.explode(
                        production_schedule.product_id, 1
                    )
                    comp_ids  = [l[0].product_id.id for l in bom_lines]
                    sched_ids = self.env['mrp.production.schedule'].search([
                        ('company_id',   '=', production_schedule.company_id.id),
                        ('warehouse_id', '=', production_schedule.warehouse_id.id),
                        ('product_id',   'in', comp_ids),
                    ]).product_id.ids
                    phantom_product_ratio = [
                        (l[0], l[0].product_qty * l[1]['qty'])
                        for l in bom_lines
                        if l[0].product_id.id not in sched_ids
                    ]
                    _logger.info(
                        "[MPS All-Periods] PATH C — %s: phantom BOM with "
                        "%d unscheduled components.",
                        production_schedule.product_id.display_name,
                        len(phantom_product_ratio),
                    )

            # ── Stock coverage for non-BOM-exploded FG products ───────────────
            if not use_bom_explosion:
                on_hand = production_schedule._mps_get_on_hand_qty(
                    production_schedule.product_id,
                    production_schedule.company_id,
                    production_schedule.warehouse_id,
                )
                open_po_by_month = production_schedule._mps_get_open_po_qty_by_month(
                    production_schedule.product_id,
                    production_schedule.company_id,
                    production_schedule.warehouse_id,
                )
                open_mo_by_month = production_schedule._mps_get_open_mo_qty_by_month(
                    production_schedule.product_id,
                    production_schedule.company_id,
                    production_schedule.warehouse_id,
                )
                _logger.info(
                    "[MPS All-Periods] FG coverage for %s — on_hand=%.4f  "
                    "open_po=%s  open_mo=%s",
                    production_schedule.product_id.display_name,
                    on_hand, list(open_po_by_month.keys()),
                    list(open_mo_by_month.keys()),
                )
            else:
                on_hand          = 0.0
                open_po_by_month = {}
                open_mo_by_month = {}

            available_balance = on_hand

            # ── Initialise per-schedule component coverage state ──────────────
            if production_schedule.id not in schedule_comp_coverage:
                schedule_comp_coverage[production_schedule.id] = {}
            comp_coverage_state = schedule_comp_coverage[production_schedule.id]

            # ── Sort periods ascending so earlier periods consume balance first ─
            sorted_forecast_ids = sorted(
                schedule_state.get('forecast_ids', []),
                key=lambda d: (
                    date_type.fromisoformat(d['date_start'])
                    if isinstance(d.get('date_start'), str)
                    else (d.get('date_start') or date_type.min)
                )
            )

            # ── Per-period processing ─────────────────────────────────────────
            for forecast_dict in sorted_forecast_ids:

                extra_forecast = dict(forecast_dict)
                for key in ('date_start', 'date_stop'):
                    val = extra_forecast.get(key)
                    if isinstance(val, str):
                        extra_forecast[key] = date_type.fromisoformat(val)

                replenish_qty = extra_forecast.get('replenish_qty', 0.0) or 0.0
                incoming_qty  = extra_forecast.get('incoming_qty',  0.0) or 0.0

                if replenish_qty <= 0.0:
                    continue

                outstanding_qty = replenish_qty - incoming_qty
                if outstanding_qty <= 0.0:
                    continue

                forecasted_on_hand = extra_forecast.get('forecasted_qty_0', 0.0) or 0.0

                date_start = extra_forecast['date_start']
                date_stop  = extra_forecast['date_stop']
                year, month = date_start.year, date_start.month
                period_key  = (year, month)

                # ── FG-level stock coverage (PATH C / PATH D only) ────────────
                if not use_bom_explosion:
                    po_arriving       = open_po_by_month.get(period_key, 0.0)
                    mo_arriving       = open_mo_by_month.get(period_key, 0.0)
                    available_balance += po_arriving + mo_arriving

                    net_required      = max(0.0, outstanding_qty - available_balance)
                    available_balance = max(0.0, available_balance - outstanding_qty)

                    _logger.info(
                        "[MPS All-Periods] %s [trigger=%s]  period %d-%02d : "
                        "replenish=%.2f  incoming(MPS)=%.2f  outstanding=%.2f  "
                        "po_arriving=%.2f  mo_arriving=%.2f  net_required=%.2f  "
                        "balance_after=%.2f",
                        production_schedule.product_id.display_name,
                        production_schedule.replenish_trigger,
                        year, month,
                        replenish_qty, incoming_qty, outstanding_qty,
                        po_arriving, mo_arriving, net_required, available_balance,
                    )

                    if net_required <= 0.0:
                        _logger.info(
                            "[MPS All-Periods] %s period %d-%02d fully covered "
                            "by on-hand / open PO / open MO — skipping.",
                            production_schedule.product_id.display_name,
                            year, month,
                        )
                        ds = extra_forecast['date_start']
                        de = extra_forecast['date_stop']
                        existing_f = production_schedule.forecast_ids.filtered(
                            lambda f, ds=ds, de=de: f.date >= ds and f.date <= de
                        )
                        if existing_f:
                            forecasts_to_set_as_launched |= existing_f
                        else:
                            forecasts_values.append({
                                'forecast_qty':           0,
                                'date':                   de,
                                'procurement_launched':   True,
                                'production_schedule_id': production_schedule.id,
                            })
                        continue

                    outstanding_qty = net_required

                origin_str = production_schedule._mps_get_replenishment_origin(
                    date_start, date_stop
                )

                # ═════════════════════════════════════════════════════════════
                # PATH A / B — BOM EXPLOSION → component RFQ line specs
                # ═════════════════════════════════════════════════════════════
                if use_bom_explosion:
                    _logger.info(
                        "[MPS All-Periods] %s period %d-%02d : exploding BOM "
                        "(qty=%.4f) for component RFQs.",
                        production_schedule.product_id.display_name,
                        year, month, outstanding_qty,
                    )
                    line_specs = production_schedule._mps_build_component_rfq_lines_from_bom(
                        product=production_schedule.product_id,
                        qty=outstanding_qty,
                        uom=production_schedule.product_uom_id,
                        date_start=date_start,
                        date_stop=date_stop,
                        company=production_schedule.company_id,
                        warehouse=production_schedule.warehouse_id,
                        comp_coverage_state=comp_coverage_state,
                    )
                    all_rfq_line_specs.extend(line_specs)

                    ds = extra_forecast['date_start']
                    de = extra_forecast['date_stop']
                    existing_f = production_schedule.forecast_ids.filtered(
                        lambda f, ds=ds, de=de: f.date >= ds and f.date <= de
                    )
                    if existing_f:
                        forecasts_to_set_as_launched |= existing_f
                    else:
                        forecasts_values.append({
                            'forecast_qty':           0,
                            'date':                   de,
                            'procurement_launched':   True,
                            'production_schedule_id': production_schedule.id,
                        })
                    continue  # ← do NOT enter accumulator for this period

                # ═════════════════════════════════════════════════════════════
                # PATH C — PHANTOM BOM → component accumulator entries
                # ═════════════════════════════════════════════════════════════
                elif phantom_bom:
                    for bom_line, qty_ratio in phantom_product_ratio:
                        comp_product = bom_line.product_id
                        raw_comp_qty = outstanding_qty * qty_ratio
                        acc_key = (
                            comp_product.id,
                            production_schedule.company_id.id,
                            production_schedule.warehouse_id.id
                            if production_schedule.warehouse_id else False,
                            year, month,
                        )
                        if acc_key not in raw_qty_accumulator:
                            comp_on_hand     = production_schedule._mps_get_on_hand_qty(
                                comp_product,
                                production_schedule.company_id,
                                production_schedule.warehouse_id,
                            )
                            comp_po_by_month = production_schedule._mps_get_open_po_qty_by_month(
                                comp_product,
                                production_schedule.company_id,
                                production_schedule.warehouse_id,
                            )
                            raw_qty_accumulator[acc_key] = {
                                'product':            comp_product,
                                'raw_qty':            raw_comp_qty,
                                'forecasted_on_hand': 0.0,
                                'uom_id':             bom_line.product_uom_id,
                                'company':            production_schedule.company_id,
                                'warehouse':          production_schedule.warehouse_id,
                                'schedule':           production_schedule,
                                '_is_component':      True,
                                '_comp_on_hand':      comp_on_hand,
                                '_comp_po_by_month':  comp_po_by_month,
                            }
                        else:
                            raw_qty_accumulator[acc_key]['raw_qty'] += raw_comp_qty

                # ═════════════════════════════════════════════════════════════
                # PATH D — STANDARD BUY-ROUTE FG → accumulator
                # ═════════════════════════════════════════════════════════════
                else:
                    acc_key = (
                        production_schedule.product_id.id,
                        production_schedule.company_id.id,
                        production_schedule.warehouse_id.id
                        if production_schedule.warehouse_id else False,
                        year, month,
                    )
                    if acc_key not in raw_qty_accumulator:
                        raw_qty_accumulator[acc_key] = {
                            'product':            production_schedule.product_id,
                            'raw_qty':            outstanding_qty,
                            'forecasted_on_hand': forecasted_on_hand,
                            'uom_id':             production_schedule.product_uom_id,
                            'company':            production_schedule.company_id,
                            'warehouse':          production_schedule.warehouse_id,
                            'schedule':           production_schedule,
                            '_is_component':      False,
                        }
                    else:
                        raw_qty_accumulator[acc_key]['raw_qty'] += outstanding_qty
                        raw_qty_accumulator[acc_key]['forecasted_on_hand'] = min(
                            raw_qty_accumulator[acc_key]['forecasted_on_hand'],
                            forecasted_on_hand,
                        )

                # ── Deferred forecast-launched tracking for accumulator entries ─
                ds = extra_forecast['date_start']
                de = extra_forecast['date_stop']
                fcast_key = (production_schedule.id, year, month)
                if fcast_key not in acc_key_to_forecast_records:
                    existing_f = production_schedule.forecast_ids.filtered(
                        lambda f, ds=ds, de=de: f.date >= ds and f.date <= de
                    )
                    acc_key_to_forecast_records[fcast_key] = (
                        production_schedule, ds, de, existing_f
                    )

        # =====================================================================
        # PRE-PASS: apply component on-hand / confirmed-PO coverage
        # =====================================================================

        comp_group_keys = defaultdict(list)
        for acc_key, acc in raw_qty_accumulator.items():
            if '_comp_on_hand' in acc:
                product_id, company_id, warehouse_id, year, month = acc_key
                comp_group_keys[(product_id, company_id, warehouse_id)].append(acc_key)

        for group_sig, keys in comp_group_keys.items():
            keys.sort(key=lambda k: (k[3], k[4]))

            first_acc        = raw_qty_accumulator[keys[0]]
            comp_on_hand     = first_acc.get('_comp_on_hand',     0.0) or 0.0
            comp_po_by_month = first_acc.get('_comp_po_by_month', {})  or {}
            available        = comp_on_hand
            component_safety_considered = False

            for acc_key in keys:
                acc = raw_qty_accumulator[acc_key]
                product_id, company_id, warehouse_id, year, month = acc_key

                po_arriving = comp_po_by_month.get((year, month), 0.0)
                available  += po_arriving
                raw_before  = acc['raw_qty']

                tmpl                   = acc['product'].product_tmpl_id
                component_safety_stock = (
                    tmpl._get_safety_stock()
                    if (
                        not component_safety_considered
                        and hasattr(tmpl, '_get_safety_stock')
                    ) else 0.0
                )
                component_safety_considered = True
                net_after  = max(0.0, raw_before + component_safety_stock - available)
                available  = max(0.0, available + net_after - raw_before)

                _logger.info(
                    "[MPS Pre-Coverage] Component %s period %d-%02d : "
                    "raw=%.4f  safety_stock=%.4f  po_arriving=%.4f  "
                    "net=%.4f  balance_after=%.4f",
                    acc['product'].display_name, year, month,
                    raw_before, component_safety_stock, po_arriving,
                    net_after, available,
                )

                acc['raw_qty'] = net_after
                acc.pop('_comp_on_hand',     None)
                acc.pop('_comp_po_by_month', None)

        # =====================================================================
        # SURPLUS CARRY-FORWARD PASS (safety-stock protected)
        # =====================================================================

        product_group_keys = defaultdict(list)
        for acc_key in list(raw_qty_accumulator.keys()):
            product_id, company_id, warehouse_id, year, month = acc_key
            product_group_keys[(product_id, company_id, warehouse_id)].append(acc_key)

        keys_to_skip = set()

        for group_sig, keys_in_group in product_group_keys.items():
            keys_in_group.sort(key=lambda k: (k[3], k[4]))
            first_acc    = raw_qty_accumulator[keys_in_group[0]]
            is_component = first_acc.get('_is_component', False)
            tmpl_check   = first_acc['product'].product_tmpl_id
            ss_check     = (
                0.0 if is_component else
                (tmpl_check._get_safety_stock() if hasattr(tmpl_check, '_get_safety_stock') else 0.0)
            )
            moq_check    = (
                tmpl_check._get_minimum_order_qty()
                if hasattr(tmpl_check, '_get_minimum_order_qty') else 0.0
            )

            if not (ss_check > 0.0 or moq_check > 0.0):
                continue

            projected_balance = (
                0.0 if is_component
                else first_acc.get('forecasted_on_hand', 0.0) or 0.0
            )

            for acc_key in keys_in_group:
                acc = raw_qty_accumulator[acc_key]
                product_id, company_id, warehouse_id, year, month = acc_key
                tmpl         = acc['product'].product_tmpl_id
                raw_qty      = acc['raw_qty']
                safety_stock = (
                    tmpl._get_safety_stock() if hasattr(tmpl, '_get_safety_stock') else 0.0
                )

                if projected_balance >= raw_qty + safety_stock:
                    projected_balance = projected_balance - raw_qty
                    keys_to_skip.add(acc_key)
                    _logger.info(
                        "[MPS Surplus Carry] %s period %d-%02d : SKIPPED "
                        "(balance %.4f ≥ demand %.4f + safety %.4f)",
                        acc['product'].display_name, year, month,
                        projected_balance + raw_qty, raw_qty, safety_stock,
                    )
                    continue

                usable_surplus = max(0.0, projected_balance - safety_stock)
                net_need       = max(0.0, raw_qty - usable_surplus)
                eff_on_hand    = projected_balance

                if is_component:
                    moq_c = (
                        tmpl._get_minimum_order_qty()
                        if hasattr(tmpl, '_get_minimum_order_qty') else 0.0
                    )
                    adjusted_qty = (
                        math.ceil(net_need / moq_c) * moq_c
                        if moq_c and moq_c > 0.0 and net_need > 0.0
                        else net_need
                    )
                else:
                    adjusted_qty = acc['schedule']._mps_adjust_procurement_qty(
                        acc['product'],
                        net_need,
                        eff_on_hand,
                        apply_safety=(acc_key == keys_in_group[0]),
                    )

                consumed          = min(raw_qty, projected_balance)
                projected_balance = projected_balance - consumed + adjusted_qty

                _logger.info(
                    "[MPS Surplus Carry] %s period %d-%02d : "
                    "raw=%.4f  balance=%.4f  safety=%.4f  usable=%.4f  "
                    "net=%.4f  ordered=%.4f  new_balance=%.4f",
                    acc['product'].display_name, year, month,
                    raw_qty, eff_on_hand, safety_stock, usable_surplus,
                    net_need, adjusted_qty, projected_balance,
                )
                acc['raw_qty'] = adjusted_qty
                acc['_procurement_qty_rules_applied'] = True

        # =====================================================================
        # Finalise accumulator → build RFQ line specs
        # =====================================================================

        for acc_key, acc in raw_qty_accumulator.items():
            product_id, company_id, warehouse_id, year, month = acc_key

            if acc_key in keys_to_skip:
                _logger.info(
                    "[MPS All-Periods] %s period %d-%02d skipped by surplus "
                    "carry — marking forecast launched.",
                    acc['product'].display_name, year, month,
                )
                fcast_key = (acc['schedule'].id, year, month)
                if fcast_key in acc_key_to_forecast_records:
                    sched, ds, de, existing_f = acc_key_to_forecast_records[fcast_key]
                    if existing_f:
                        forecasts_to_set_as_launched |= existing_f
                    else:
                        forecasts_values.append({
                            'forecast_qty':           0,
                            'date':                   de,
                            'procurement_launched':   True,
                            'production_schedule_id': sched.id,
                        })
                continue

            if acc['raw_qty'] <= 0.0:
                _logger.info(
                    "[MPS All-Periods] %s period %d-%02d fully covered — skip.",
                    acc['product'].display_name, year, month,
                )
                continue

            eff_on_hand  = acc.get('_projected_on_hand', acc.get('forecasted_on_hand', 0.0))
            is_component = acc.get('_is_component', False)

            if acc.get('_procurement_qty_rules_applied'):
                adjusted_qty = acc['raw_qty']
            elif is_component:
                moq_c = (
                    acc['product'].product_tmpl_id._get_minimum_order_qty()
                    if hasattr(acc['product'].product_tmpl_id, '_get_minimum_order_qty') else 0.0
                )
                adjusted_qty = (
                    math.ceil(acc['raw_qty'] / moq_c) * moq_c
                    if moq_c and moq_c > 0.0 and acc['raw_qty'] > 0.0
                    else acc['raw_qty']
                )
            else:
                group_key = (product_id, company_id, warehouse_id)
                first_key = product_group_keys.get(group_key, [acc_key])[0]
                adjusted_qty = acc['schedule']._mps_adjust_procurement_qty(
                    acc['product'],
                    acc['raw_qty'],
                    eff_on_hand,
                    apply_safety=(acc_key == first_key),
                )

            _logger.info(
                "[MPS All-Periods] FINAL qty for %s  period=%d-%02d : "
                "raw=%.4f → adjusted=%.4f  (eff_on_hand=%.4f)%s",
                acc['product'].display_name, year, month,
                acc['raw_qty'], adjusted_qty, eff_on_hand,
                '  [component: MOQ-only]' if is_component else '',
            )

            all_rfq_line_specs.append({
                'product':     acc['product'],
                'qty':         adjusted_qty,
                'uom':         acc['uom_id'],
                'company':     acc['company'],
                'warehouse':   acc['warehouse'],
                'date_needed': date_type(year, month, 1),
                'year':        year,
                'month':       month,
            })

        # ── Mark accumulator forecast records as launched ─────────────────────
        for fcast_key, (sched, ds, de, existing_f) in acc_key_to_forecast_records.items():
            if existing_f:
                forecasts_to_set_as_launched |= existing_f
            else:
                forecasts_values.append({
                    'forecast_qty':           0,
                    'date':                   de,
                    'procurement_launched':   True,
                    'production_schedule_id': sched.id,
                })

        # ── Nothing to do? ────────────────────────────────────────────────────
        if not all_rfq_line_specs:
            _logger.info("[MPS All-Periods] No outstanding lines to order.")
            forecasts_to_set_as_launched.write({'procurement_launched': True})
            if forecasts_values:
                self.env['mrp.product.forecast'].create(forecasts_values)
            return False

        # ── Create RFQs ───────────────────────────────────────────────────────
        created_rfqs = self._mps_create_rfqs(all_rfq_line_specs)

        _logger.info(
            "[MPS All-Periods] Complete. %d RFQ(s) created: %s",
            len(created_rfqs), [r.name for r in created_rfqs],
        )

        # ── Write procurement_launched flags ──────────────────────────────────
        forecasts_to_set_as_launched.write({'procurement_launched': True})
        if forecasts_values:
            self.env['mrp.product.forecast'].create(forecasts_values)
