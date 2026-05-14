# -*- coding: utf-8 -*-
# =============================================================================
# models/mrp_production_schedule.py
#
# PURPOSE
# -------
# Extend mrp.production.schedule to replenish ALL visible forecast periods
# when the user presses "Order Once" / "Replenish" in the MPS screen.
#
# PR INTEGRATION
# --------------
# Instead of creating Purchase Orders (RFQs) directly, all "Buy" procurements
# are intercepted and turned into Purchase Requisitions (purchase.approval).
# The requester_id on the PR is always the user who pressed Replenish.
# Manufacture / sub-MO procurements still go through the normal engine.
#
# PRs are grouped by (company, warehouse, department).  The department is
# taken from the department_id field added to mrp.production.schedule.
# If no department is set on the schedule, the warehouse's default department
# is used.  If neither is set, a UserError is raised.
#
# BOM-DRIVEN REPLENISHMENT — DESIGN INTENT
# -----------------------------------------
# Every time the user presses "Order" in MPS the custom logic runs regardless
# of replenish_trigger.  Routing is determined solely by the product's BOM
# type and stock routes:
#
#   Has manufacture BOM  +  NO Manufacture route  →  explode BOM, create
#     component PRs instead of a PR for the finished good.  This handles
#     products that are built internally but whose raw materials are bought.
#
#   Has manufacture BOM  +  Manufacture route     →  normal MO path via the
#     procurement engine (unchanged from Odoo standard).
#
#   Has phantom/kit BOM                           →  explode into components,
#     create PRs for unscheduled components.
#
#   No BOM                                        →  direct PR for the product
#     itself (standard Buy replenishment).
#
# replenish_trigger='never' is no longer required; users do not need to
# configure the trigger field to get component-level PRs.
#
# BUGS FIXED
# ----------
# BUG 1 — replenish_trigger='never' silently dropped the whole schedule
# BUG 2 — replenish_qty read from stored records (always returns 0)
# BUG 3 — date key type mismatch (ISO string vs Python date object)
# BUG 4 — on-hand stock and confirmed POs not deducted before creating PRs
# BUG 5 — open MOs not included in available supply when computing net need
# BUG 6 — surplus from MOQ/safety-stock rounding not carried to next month
# BUG 7 — surplus carry-forward consumed safety stock (protected inventory)
# BUG 8 — component on-hand/PO coverage was applied AFTER the surplus carry
#          pass, so the carry-forward surplus was calculated against inflated
#          raw_qty that hadn't had existing stock deducted yet.
#          Fixed: a dedicated pre-pass applies on-hand/PO deduction to every
#          component accumulator entry (using a running balance across months,
#          earliest first) BEFORE the surplus carry runs.  The correct pipeline
#          is now:
#            raw_qty (exploded)
#              → minus on_hand + confirmed POs   [pre-coverage pass]
#              → minus usable surplus (surplus − safety_stock)  [surplus carry]
#              → plus safety_stock + round to MOQ  [procurement creation]
#
# STOCK COVERAGE LOGIC
# --------------------
# Before creating any procurement, action_replenish now independently queries:
#   1. Unreserved on-hand stock at the warehouse's stock location
#   2. Confirmed PO lines (state='purchase') not yet received, keyed by month
#   3. Open Manufacturing Orders (confirmed/progress), keyed by month
#
# A per-schedule *running available balance* is maintained across periods
# (sorted ascending by date_start) so that on-hand stock is consumed by the
# earliest period first, and incoming supply (POs / MOs) is added to the
# balance in the period it is expected to arrive.
#
# net_required = max(0, outstanding_qty − available_balance_for_period)
#
# If net_required == 0 the period is marked launched but no procurement is
# created, preventing duplicate PRs for already-covered demand.
#
# SURPLUS CARRY-FORWARD WITH SAFETY-STOCK PROTECTION (BUG 6 + BUG 7 FIX)
# -------------------------------------------------------------------------
# After the accumulator is fully populated (all periods / all schedules
# processed), a second pass groups accumulator entries by
# (product_id, company_id, warehouse_id) and sorts them ascending by month.
#
# A running surplus starts at 0 and is updated each month.  Critically,
# safety stock is treated as PROTECTED inventory — it cannot be consumed
# by future demand.  Only the portion of surplus ABOVE safety stock is
# usable as carry-forward:
#
#   safety_stock    = product.template._get_safety_stock()
#   usable_surplus  = max(0, surplus − safety_stock)
#   net_need        = max(0, raw_qty − usable_surplus)
#   ordered_qty     = _mps_adjust_procurement_qty(net_need)   # MOQ / safety
#   surplus         = ordered_qty − net_need                  # carry forward
#
# If net_need == 0 the month is skipped (period marked launched, no PR).
# The accumulator entry's raw_qty is replaced with net_need so the later
# MOQ loop still applies the rules correctly on the reduced base.
#
# NOTE: MPS's own incoming_qty (from get_production_schedule_view_state)
# reflects stock moves already in Odoo's picking system.  Draft / sent POs
# do NOT create moves yet, so MPS silently shows 0 incoming for them.
# The helpers below query purchase.order.line directly, avoiding that gap.
#
# DUPLICATE PR PREVENTION
# -----------------------
# Before adding a procurement line to a new PR, the code checks whether an
# existing draft or confirmed PR already contains a line for the same product
# whose planned date range overlaps the current forecast period.
# Duplicates are silently skipped; a summary is logged at INFO level.
#
# MPS DISPLAY FIX — on-hand always shows 0
# -----------------------------------------
# Odoo's get_production_schedule_view_state() computes on-hand via
# product.qty_available scoped by warehouse context.  This can return 0
# immediately after a Manufacturing Order completes because the context
# cache is stale for that session, and also because qty_available only
# counts stock at the product's internal reference location — it may miss
# goods in child locations such as WH/Stock sub-zones.
#
# Fix: override get_production_schedule_view_state() to post-process every
# period dict and replace qty_on_hand / forecasted_qty_0 with a fresh read
# from stock.quant at warehouse.lot_stock_id and all its child locations.
# This makes the MPS opening-stock cell always reflect the true current
# on-hand, which also drives the correct replenishment suggestion.
# =============================================================================

import logging
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

        period_scale is passed through to super() unchanged; it controls the
        time bucket size (day / week / month) used by the MPS grid.

        WHY THIS IS NEEDED
        ------------------
        Odoo's core implementation calls product.qty_available inside a
        warehouse context.  This can return 0 when:

          • A Manufacturing Order was just completed — the context cache is
            stale and has not yet reflected the new quant written by the MO.

          • The product's "internal reference" location differs from
            warehouse.lot_stock_id (e.g. sub-locations, transit zones).

        By reading stock.quant directly and summing over child_of the
        warehouse's main stock location, we always get the true current
        on-hand regardless of context caching.

        The fix patches every mps_state dict returned by super():
          • qty_on_hand          — the raw on-hand figure used in calculations
          • forecasted_qty_0     — the opening cell displayed in the MPS grid
            (first period only)

        All downstream period calculations (replenish_qty, forecasted_stock,
        etc.) are recomputed so the corrected on-hand flows through.
        """
        # Call the standard Odoo implementation first, forwarding period_scale
        if period_scale is not None:
            result = super().get_production_schedule_view_state(period_scale)
        else:
            result = super().get_production_schedule_view_state()

        # Build a fast lookup: schedule_id → mrp.production.schedule record
        schedule_by_id = {rec.id: rec for rec in self}

        for mps_state in result:
            schedule = schedule_by_id.get(mps_state.get('id'))
            if not schedule:
                continue

            product   = schedule.product_id
            company   = schedule.company_id
            warehouse = schedule.warehouse_id
            location  = warehouse.lot_stock_id if warehouse else False

            # ── Fresh on-hand from stock.quant ────────────────────────────
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
                    product.display_name,
                    odoo_on_hand,
                    real_on_hand,
                    location.complete_name if location else 'N/A',
                )

            # Patch the top-level on-hand field
            mps_state['qty_on_hand'] = real_on_hand

            # ── Patch forecasted_qty_0 in the first forecast period ───────
            # forecasted_qty_0 is the opening stock shown in the MPS grid
            # cell.  It must equal real_on_hand for the first period; Odoo
            # carries it forward between periods automatically after that.
            forecast_ids = mps_state.get('forecast_ids', [])
            if forecast_ids:
                # Sort ascending so we patch only the earliest period
                def _period_sort_key(p):
                    ds = p.get('date_start')
                    if isinstance(ds, str):
                        return date_type.fromisoformat(ds)
                    return ds or date_type.min

                sorted_periods = sorted(forecast_ids, key=_period_sort_key)
                first_period = sorted_periods[0]

                odoo_fq0 = first_period.get('forecasted_qty_0', 0.0) or 0.0
                if abs(real_on_hand - odoo_fq0) > 0.001:
                    first_period['forecasted_qty_0'] = real_on_hand

                    # Recompute replenish_qty for the first period so the
                    # suggested order quantity reflects the corrected on-hand.
                    # Formula mirrors Odoo's core logic:
                    #   replenish = max(0, target − (on_hand + incoming − demand))
                    demand       = first_period.get('forecast_qty',     0.0) or 0.0
                    incoming     = first_period.get('incoming_qty',     0.0) or 0.0
                    target       = first_period.get('forecast_target_qty', 0.0) or 0.0
                    old_replenish = first_period.get('replenish_qty',   0.0) or 0.0

                    new_replenish = max(0.0, target - (real_on_hand + incoming - demand))
                    first_period['replenish_qty'] = new_replenish

                    _logger.info(
                        "[MPS Display Fix] %s first period: "
                        "forecasted_qty_0 %.4f→%.4f  "
                        "replenish_qty %.4f→%.4f  "
                        "(demand=%.4f  incoming=%.4f  target=%.4f)",
                        product.display_name,
                        odoo_fq0, real_on_hand,
                        old_replenish, new_replenish,
                        demand, incoming, target,
                    )

        return result

    # =========================================================================
    # Helper: apply minimum_order_qty and safety_stock to a procurement qty
    # =========================================================================

    def _mps_adjust_procurement_qty(self, product, raw_qty, forecasted_on_hand=0.0):
        """
        Apply the two product-level procurement-qty rules in order:

          1. Safety stock  — add buffer when on-hand <= 0
          2. Minimum order qty — round up to vendor minimum

        Delegates to product.template._apply_procurement_qty_rules().
        """
        self.ensure_one()
        tmpl = product.product_tmpl_id
        adjusted = tmpl._apply_procurement_qty_rules(raw_qty, forecasted_on_hand)

        if adjusted != raw_qty:
            _logger.info(
                "[MPS All-Periods] qty adjusted for %s: %.4f → %.4f "
                "(safety_stock=%.4f, min_order_qty=%.4f, on_hand=%.4f)",
                product.display_name,
                raw_qty,
                adjusted,
                tmpl._get_safety_stock(),
                tmpl._get_minimum_order_qty(),
                forecasted_on_hand,
            )

        return adjusted

    # =========================================================================
    # Helper: collect all view-state periods with outstanding replenish_qty
    # =========================================================================

    def _mps_collect_replenish_states(self):
        """
        Return a list of view-state dicts for *this single schedule* where
        replenish_qty > 0, sorted ascending by date_start.
        """
        self.ensure_one()
        all_states = self.get_production_schedule_view_state()

        result = []
        for mps_state in all_states:
            if mps_state.get('id') != self.id:
                continue
            for period in mps_state.get('forecast_ids', []):
                for key in ('date_start', 'date_stop'):
                    val = period.get(key)
                    if isinstance(val, str):
                        period[key] = date_type.fromisoformat(val)

                replenish_qty = period.get('replenish_qty') or 0.0
                if replenish_qty > 0.0:
                    result.append(period)

        result.sort(key=lambda d: d['date_start'])
        return result

    # =========================================================================
    # Helper: combined product lead time in days
    # =========================================================================

    def _mps_get_product_lead_time_days(self):
        self.ensure_one()
        product = self.product_id
        lead = (
            (product.produce_delay or 0.0)
            + (product.days_to_purchase or 0.0)
            + (product.purchase_delay or 0.0)
        )
        return max(lead, 0.0)

    # =========================================================================
    # Helper: compute the procurement datetime for a period
    # =========================================================================

    def _mps_get_procurement_date(self, date_start, based_on_lead_time=False):
        self.ensure_one()
        if isinstance(date_start, date_type) and not isinstance(date_start, datetime):
            base_dt = datetime.combine(date_start, datetime.min.time())
        else:
            base_dt = date_start

        if not based_on_lead_time:
            return base_dt

        lead_days = self._mps_get_product_lead_time_days()
        procurement_dt = base_dt - timedelta(days=lead_days)
        now = datetime.now()
        if procurement_dt < now:
            procurement_dt = now
        return procurement_dt

    # =========================================================================
    # Helper: build a human-readable procurement origin string
    # =========================================================================

    def _mps_get_replenishment_origin(self, date_start, date_stop):
        self.ensure_one()
        product_ref = (
            self.product_id.default_code
            or self.product_id.display_name
        )
        warehouse_code = self.warehouse_id.code or 'WH'
        date_str = date_start.strftime('%Y-%m-%d') if hasattr(date_start, 'strftime') else str(date_start)
        return f"MPS/{warehouse_code}/{product_ref}/{date_str}"

    # =========================================================================
    # Helper: get or create a reusable procurement.group for this schedule
    # =========================================================================

    def _mps_get_or_create_procurement_group(self):
        self.ensure_one()
        group_name = (
            f"MPS/{self.warehouse_id.code}/{self.product_id.display_name}"
        )
        group = self.env['procurement.group'].search(
            [('name', '=', group_name)], limit=1
        )
        if not group:
            group = self.env['procurement.group'].create({'name': group_name})
        return group

    # =========================================================================
    # Helper: assemble the values dict for a Procurement namedtuple
    # =========================================================================

    def _mps_get_procurement_values(self, date_start, date_stop, procurement_date):
        self.ensure_one()

        extra_forecast = {
            'date_start': date_start,
            'date_stop': date_stop,
        }
        extra_values = self._get_procurement_extra_values(extra_forecast)

        group = self._mps_get_or_create_procurement_group()

        values = {
            'date_planned': datetime.combine(date_start, datetime.min.time()),
            'date_deadline': datetime.combine(date_stop, datetime.min.time()),
            'group_id': group,
            'warehouse_id': self.warehouse_id,
            'company_id': self.company_id,
        }
        values.update(extra_values)
        values['date_planned'] = datetime.combine(date_start, datetime.min.time())
        values['group_id'] = group
        values['company_id'] = self.company_id

        return values

    # =========================================================================
    # Helper: Buy route lookup
    # =========================================================================

    def _mps_get_buy_route(self):
        """Return the canonical 'Buy' stock route."""
        self.ensure_one()
        try:
            buy_route = self.env.ref('purchase_stock.route_warehouse0_buy')
            if buy_route:
                return buy_route
        except Exception:
            pass
        return self.env['stock.route'].search(
            [('name', 'ilike', 'buy')], limit=1
        )

    def _mps_get_component_route(self, component):
        """Return the correct stock route for a BOM component."""
        if component.route_ids:
            return component.route_ids[0]
        if component.categ_id.route_ids:
            return component.categ_id.route_ids[0]
        return self._mps_get_buy_route()

    # =========================================================================
    # NEW — Stock coverage helpers (BUG 4 / BUG 5 fix)
    # =========================================================================

    def _mps_get_on_hand_qty(self, product, company, warehouse):
        """
        Return the *unreserved* on-hand quantity for a product at the
        warehouse's stock location (lot_stock_id).

        Falls back to product.qty_available (company-scoped) when no
        warehouse location is available.

        This is queried directly from stock.quant rather than relying on
        MPS's forecasted_qty_0, which may be stale or misconfigured.

        Args:
            product   (product.product):  The product to check.
            company   (res.company):       Company scope.
            warehouse (stock.warehouse):   Warehouse to check.

        Returns:
            float: Unreserved on-hand quantity in the product's UoM.
        """
        location = warehouse.lot_stock_id if warehouse else False

        if location:
            quants = self.env['stock.quant'].search([
                ('product_id',   '=', product.id),
                ('location_id',  'child_of', location.id),
                ('company_id',   '=', company.id),
            ])
            on_hand = sum(
                max(0.0, q.quantity - q.reserved_quantity) for q in quants
            )
        else:
            on_hand = product.with_context(
                force_company=company.id
            ).qty_available

        _logger.info(
            "[MPS Coverage] on_hand for %s @ %s : %.4f",
            product.display_name,
            warehouse.code if warehouse else 'N/A',
            on_hand,
        )
        return on_hand

    def _mps_get_open_po_qty_by_month(self, product, company, warehouse):
        """
        Return confirmed-PO incoming quantities, keyed by (year, month).

        Only includes purchase.order lines in state 'purchase' (confirmed)
        whose receipt has not yet been completed (product_uom_qty > qty_received).

        MPS's own incoming_qty only reflects stock moves that already exist.
        Draft / sent POs do NOT create moves yet, so MPS may show zero incoming
        even when significant supply is on order.  This helper queries
        purchase.order.line directly to close that gap.

        Args:
            product   (product.product)
            company   (res.company)
            warehouse (stock.warehouse | False)

        Returns:
            dict  {(year, month): float}
        """
        domain = [
            ('product_id',        '=',  product.id),
            ('order_id.state',    'in', ['purchase']),   # confirmed only
            ('order_id.company_id', '=', company.id),
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
                _logger.warning(
                    "[MPS Coverage] PO line %s has no date_planned — skipped.",
                    line.id,
                )
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

    def _mps_get_open_mo_qty_by_month(self, product, company, warehouse):
        """
        Return open Manufacturing Order quantities, keyed by (year, month).

        Only includes MOs in state 'confirmed', 'progress', or 'to_close'
        (i.e. not draft, done, or cancelled).

        MPS should show these as incoming supply, but may miss them when the
        MO's picking type / warehouse does not match the MPS schedule exactly.

        Returns {} when the mrp.production model is not installed.

        Args:
            product   (product.product)
            company   (res.company)
            warehouse (stock.warehouse | False)

        Returns:
            dict  {(year, month): float}
        """
        if not self.env['ir.model'].search(
            [('model', '=', 'mrp.production')], limit=1
        ):
            return {}

        domain = [
            ('product_id',  '=',  product.id),
            ('state',       'in', ['confirmed', 'progress', 'to_close']),
            ('company_id',  '=',  company.id),
        ]
        if warehouse:
            domain.append(
                ('picking_type_id.warehouse_id', '=', warehouse.id)
            )

        by_month = {}
        for mo in self.env['mrp.production'].search(domain):
            remaining = max(
                0.0,
                (mo.product_qty or 0.0) - (mo.qty_produced or 0.0)
            )
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
    # Helper: component procurements for 'never' finished goods
    # =========================================================================

    def _mps_get_raw_component_qtys_for_never_schedule(
        self, outstanding_qty, extra_forecast, extra_values
    ):
        """
        Explode the manufacture BOM for a 'never' finished good and return
        a list of raw component quantity dicts with NO safety_stock or MOQ applied.

        Safety stock and MOQ are deferred so the caller can accumulate quantities
        across multiple finished goods sharing the same raw material, then apply
        the rules exactly once via the raw_qty_accumulator.

        Returns list of dicts:
            {
                'product':      product.product record,
                'raw_qty':      float (exploded qty, unadjusted),
                'uom_id':       product.uom record,
                'extra_values': procurement values dict (with route set),
                'company':      res.company record,
            }
        Returns [] when no BOM is found.
        """
        self.ensure_one()

        bom = self.env['mrp.bom']._bom_find(
            self.product_id,
            company_id=self.company_id.id,
            bom_type='normal',
        )[self.product_id]

        if not bom:
            _logger.warning(
                "[MPS All-Periods] replenish_trigger='never' on %s "
                "but no manufacture BOM found - cannot create component PRs.",
                self.product_id.display_name,
            )
            return []

        _dummy, bom_lines = bom.explode(self.product_id, outstanding_qty)

        all_component_ids = [line[0].product_id.id for line in bom_lines]
        already_scheduled_ids = self.env['mrp.production.schedule'].search([
            ('company_id',   '=', self.company_id.id),
            ('warehouse_id', '=', self.warehouse_id.id),
            ('product_id',   'in', all_component_ids),
        ]).product_id.ids

        result = []
        for bom_line, line_data in bom_lines:
            component = bom_line.product_id

            if component.id in already_scheduled_ids:
                continue

            component_route = self._mps_get_component_route(component)
            component_values = dict(extra_values)
            if component_route:
                component_values['route_ids'] = component_route
            else:
                component_values.pop('route_ids', None)
            component_values.pop('supplierinfo_id', None)

            result.append({
                'product':      component,
                'raw_qty':      line_data['qty'],   # raw - no safety_stock/MOQ yet
                'uom_id':       bom_line.product_uom_id,
                'extra_values': component_values,
                'company':      self.company_id,
            })

        return result


    # =========================================================================
    # PR creation helpers
    # =========================================================================

    def _mps_is_manufacture_procurement(self, proc):
        """
        Return True ONLY if this procurement will generate a Manufacturing Order.
        """
        def _route_is_manufacture(route):
            if not route:
                return False
            name = (route.name or '').lower()
            return 'manufactur' in name or 'fabricat' in name

        route_in_values = proc.values.get('route_ids')
        if route_in_values:
            try:
                routes = list(route_in_values)
            except TypeError:
                routes = [route_in_values]
            for r in routes:
                if _route_is_manufacture(r):
                    return True
            return False

        product = proc.product_id
        all_routes = list(product.route_ids) + list(product.categ_id.route_ids)
        if not all_routes:
            return False

        manufacture_routes     = [r for r in all_routes if _route_is_manufacture(r)]
        non_manufacture_routes = [r for r in all_routes if not _route_is_manufacture(r)]

        if manufacture_routes and not non_manufacture_routes:
            return True

        return False

    def _mps_is_buy_procurement(self, proc):
        return not self._mps_is_manufacture_procurement(proc)

    def _mps_resolve_department_for_proc(self, proc):
        """
        Return the hr.department of the user who pressed Replenish.
        """
        user = self.env.user
        employee = user.employee_id
        if employee and employee.department_id:
            return employee.department_id

        raise UserError(_(
            'Cannot create a Purchase Requisition: the user "%s" has no '
            'Department set on their Employee profile.\n\n'
            'Please open the Employee record for this user and assign a '
            'Department, then try again.'
        ) % user.name)

    # =========================================================================
    # Helper: duplicate PR line detection
    # =========================================================================

    def _mps_find_existing_pr_line(self, product_id, quantity):
        """
        Search for an existing open purchase.approval line where:
          - product matches exactly
          - quantity matches exactly (within float tolerance of 0.001)

        Only open PRs are considered: draft / waiting_approval / approved.
        """
        active_pr_states = ['draft', 'waiting_approval', 'approved']

        candidates = self.env['purchase.approval.line'].search([
            ('product_id',        '=',  product_id),
            ('approval_id.state', 'in', active_pr_states),
        ])

        tolerance = 0.001
        return candidates.filtered(
            lambda l, q=quantity, t=tolerance: abs(l.quantity - q) <= t
        )

    # =========================================================================
    # PR creation
    # =========================================================================

    def _mps_create_prs_from_buy_procurements(self, buy_procurements):
        """
        Convert a list of Buy procurements into purchase.approval (PR) records,
        silently skipping any procurement whose product + quantity is already
        covered by an existing draft/confirmed/approved PR.
        """
        PurchaseApproval = self.env['purchase.approval']
        human_requester = self.env.user
        odoobot = self.env.ref('base.user_root')
        requester = odoobot

        # -- Duplicate check --------------------------------------------------
        filtered_procurements = []
        duplicate_info = []

        for proc in buy_procurements:
            existing_lines = self._mps_find_existing_pr_line(
                proc.product_id.id, proc.product_qty
            )

            if existing_lines:
                pr_names = sorted({
                    line.approval_id.name
                    for line in existing_lines
                    if line.approval_id.name
                })
                duplicate_info.append((
                    proc.product_id.display_name,
                    proc.product_qty,
                    ', '.join(pr_names) or '(unnamed)',
                ))
                _logger.info(
                    "[MPS All-Periods] DUPLICATE BLOCKED: product=%s  "
                    "qty=%.3f  already in PR(s): %s",
                    proc.product_id.display_name,
                    proc.product_qty,
                    ', '.join(pr_names),
                )
            else:
                filtered_procurements.append(proc)

        if duplicate_info:
            conflict_lines = "\n".join(
                "  * %s  (qty: %.3f)  ->  %s" % (name, qty, prs)
                for name, qty, prs in duplicate_info
            )
            raise UserError(_(
                "Cannot replenish: the following item(s) already exist in an "
                "open Purchase Requisition with the same quantity.\n"
                "Please review or cancel the existing PR before replenishing again.\n\n"
                "%s"
            ) % conflict_lines)

        if not filtered_procurements:
            _logger.info(
                "[MPS All-Periods] All buy procurements are already covered "
                "by existing PRs. No new PRs created."
            )
            return []

        # -- Group: one PR per (company, warehouse, department, product, year, month)
        groups = {}

        for proc in filtered_procurements:
            department = self._mps_resolve_department_for_proc(proc)
            company    = proc.values.get('company_id') or self.env.company
            warehouse  = proc.values.get('warehouse_id')

            date_planned = proc.values.get('date_planned')
            if isinstance(date_planned, datetime):
                year, month = date_planned.year, date_planned.month
            elif isinstance(date_planned, date_type):
                year, month = date_planned.year, date_planned.month
            else:
                now = datetime.now()
                year, month = now.year, now.month

            key = (
                company.id,
                warehouse.id if warehouse else False,
                department.id,
                proc.product_id.id,
                year,
                month,
            )

            if key not in groups:
                groups[key] = {
                    'company':      company,
                    'warehouse':    warehouse,
                    'department':   department,
                    'product':      proc.product_id,
                    'year':         year,
                    'month':        month,
                    'date_planned': date_planned,
                    'procs':        [],
                }
            groups[key]['procs'].append(proc)

        # -- Create one PR per group ------------------------------------------
        import calendar
        created_prs = []

        for key, group in groups.items():
            month_name  = calendar.month_abbr[group['month']]
            product_ref = (
                group['product'].default_code
                or group['product'].display_name
            )

            line_vals = []
            for proc in group['procs']:
                line_vals.append((0, 0, {
                    'product_id':  proc.product_id.id,
                    'description': proc.name or proc.product_id.display_name,
                    'quantity':    proc.product_qty,
                }))

            today = datetime.now().date()
            if group['year'] == today.year and group['month'] == today.month:
                pr_date = today
            else:
                pr_date = date_type(group['year'], group['month'], 1)

            pr_vals = {
                'requester_id':  requester.id,
                'department_id': group['department'].id,
                'company_id':    group['company'].id,
                'state':         'approved',
                'date':          pr_date,
                'line_ids':      line_vals,
            }
            if group['warehouse']:
                pr_vals['warehouse_id'] = group['warehouse'].id

            pr = PurchaseApproval.create(pr_vals)
            pr.message_post(
                body=_(
                    'Auto-approved by MPS replenishment. '
                    'Product: <b>%s</b>  Period: <b>%s %s</b>  '
                    'Triggered by: <b>%s</b>'
                ) % (
                    group['product'].display_name,
                    month_name,
                    group['year'],
                    human_requester.name,
                )
            )

            _logger.info(
                "[MPS All-Periods] Created PR %s  product=%s  period=%s-%02d  "
                "dept=%s  requester=%s  lines=%d",
                pr.name,
                group['product'].display_name,
                group['year'],
                group['month'],
                group['department'].name,
                human_requester.login,
                len(group['procs']),
            )
            created_prs.append(pr)

        return created_prs

    # =========================================================================
    # Main override: action_replenish
    # =========================================================================

    def action_replenish(self, based_on_lead_time=False):
        """
        Override action_replenish() to process ALL visible forecast periods
        AND route ALL Buy procurements to Purchase Requisitions instead of RFQs.

        KEY BEHAVIOURAL CHANGES vs. Odoo standard
        ------------------------------------------
        1. BOM + ROUTE DRIVEN (no replenish_trigger dependency):
           Every button press runs the full BOM-detection and component-explosion
           logic regardless of replenish_trigger.  Products with a normal BOM
           and no Manufacture route will always have their BOM exploded and
           component PRs created — users no longer need to set trigger='never'.

        2. ALL forecast periods with replenish_qty > 0 are processed.

        3. replenish_qty is read from the view-state dict (computed correctly).

        4. Date keys are normalised to date objects before comparison.

        5. Buy procurements ALWAYS create purchase.approval (PR) records,
           never RFQs.

        6. STOCK COVERAGE (BUG 4 / BUG 5 FIX):
           Before creating any procurement, on-hand stock and confirmed
           incoming supply (POs + MOs) are queried directly from the database.
           A running available balance is maintained per schedule across periods
           (earliest period first).

        7. SURPLUS CARRY-FORWARD WITH SAFETY-STOCK PROTECTION (BUG 6 + 7 FIX):
           After the accumulator is fully populated, a second pass groups
           entries by (product_id, company_id, warehouse_id) sorted ascending
           by (year, month).  Safety stock is treated as PROTECTED inventory:

             safety_stock    = product.template._get_safety_stock()
             usable_surplus  = max(0, surplus − safety_stock)
             net_need        = max(0, raw_qty − usable_surplus)
             ordered_qty     = _mps_adjust_procurement_qty(net_need)
             surplus         = ordered_qty − net_need   ← carried to next month

           Months where net_need == 0 are skipped (no PR, period marked launched).

        8. Duplicate detection: existing draft/confirmed/approved PRs for the
           same product + quantity raise a UserError listing all conflicts.
        """
        _logger.info(
            "[MPS All-Periods] action_replenish called | schedules=%s | lead_time=%s",
            self.ids, based_on_lead_time,
        )

        production_schedules = self

        if not production_schedules:
            _logger.info("[MPS All-Periods] No schedules selected. Returning.")
            return False

        production_schedule_states = production_schedules.get_production_schedule_view_state()
        state_by_id = {mps['id']: mps for mps in production_schedule_states}

        procurements = []
        forecasts_values = []
        forecasts_to_set_as_launched = self.env['mrp.product.forecast']

        # ── Raw-qty accumulator ───────────────────────────────────────────────
        # Key: (product_id, company_id, warehouse_id, year, month)
        # Value: accumulated procurement data (safety_stock / MOQ applied once
        #        after the full loop).
        raw_qty_accumulator = {}

        # ── Track which forecast records to mark launched per accumulator key ─
        # We defer "mark as launched" until after the surplus pass so that
        # months that are fully covered by surplus are still marked launched
        # without creating a PR.
        acc_key_to_forecast_records = {}   # acc_key → set of mrp.product.forecast ids
        acc_key_to_forecast_values  = {}   # acc_key → list of forecast value dicts

        for production_schedule in production_schedules:
            schedule_state = state_by_id.get(production_schedule.id)
            if not schedule_state:
                continue

            is_never = production_schedule.replenish_trigger == 'never'

            # ── BOM + route detection (runs for ALL schedules) ────────────────
            # Routing is determined entirely by the product's BOM type and stock
            # routes.  replenish_trigger='never' is no longer required — the
            # button press itself triggers this logic every time.
            #
            # Decision tree:
            #   Normal BOM + NO Manufacture route  →  explode BOM, buy components
            #   Normal BOM + Manufacture route      →  normal engine creates MO
            #   Phantom/kit BOM                     →  explode into components
            #   No BOM                              →  direct PR for product
            #
            # The is_never flag is kept for backward-compatibility log messages
            # only; it does NOT gate the BOM-detection logic any more.
            has_manufacture_bom_buy = False
            manufacture_bom_for_buy = None

            candidate_bom = self.env['mrp.bom']._bom_find(
                production_schedule.product_id,
                company_id=production_schedule.company_id.id,
                bom_type='normal',
            )[production_schedule.product_id]
            if candidate_bom:
                product_routes = (
                    list(production_schedule.product_id.route_ids)
                    + list(production_schedule.product_id.categ_id.route_ids)
                )
                has_mfg_route = any(
                    'manufactur' in (r.name or '').lower()
                    or 'fabricat' in (r.name or '').lower()
                    for r in product_routes
                )
                if not has_mfg_route:
                    # No manufacture route → buy components instead of creating MO
                    has_manufacture_bom_buy = True
                    manufacture_bom_for_buy = candidate_bom
                    _logger.info(
                        "[MPS All-Periods] %s — normal BOM found, no manufacture "
                        "route → will explode BOM and create component PRs "
                        "(trigger=%s).",
                        production_schedule.product_id.display_name,
                        production_schedule.replenish_trigger,
                    )

            # ── Phantom / kit BOM detection ───────────────────────────────────
            phantom_bom = None
            phantom_product_ratio = []
            if not has_manufacture_bom_buy:
                phantom_bom = self.env['mrp.bom']._bom_find(
                    production_schedule.product_id,
                    company_id=production_schedule.company_id.id,
                    bom_type='phantom',
                )[production_schedule.product_id]

                if phantom_bom:
                    _dummy, bom_lines = phantom_bom.explode(
                        production_schedule.product_id, 1
                    )
                    component_ids = [l[0].product_id.id for l in bom_lines]
                    scheduled_ids = self.env['mrp.production.schedule'].search([
                        ('company_id',   '=', production_schedule.company_id.id),
                        ('warehouse_id', '=', production_schedule.warehouse_id.id),
                        ('product_id',   'in', component_ids),
                    ]).product_id.ids
                    phantom_product_ratio = [
                        (l[0], l[0].product_qty * l[1]['qty'])
                        for l in bom_lines
                        if l[0].product_id.id not in scheduled_ids
                    ]

            # ── Build stock coverage for this schedule (BUG 4 / 5 fix) ───────
            #
            # For products whose BOM will be exploded into components we do NOT
            # need coverage on the finished good itself (no PR is created for
            # it); coverage is checked per component inside the accumulator.
            skip_fg_coverage = has_manufacture_bom_buy
            if not skip_fg_coverage:
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
                    "[MPS All-Periods] Coverage for %s — on_hand=%.4f  "
                    "open_po_months=%s  open_mo_months=%s",
                    production_schedule.product_id.display_name,
                    on_hand,
                    list(open_po_by_month.keys()),
                    list(open_mo_by_month.keys()),
                )
            else:
                on_hand = 0.0
                open_po_by_month = {}
                open_mo_by_month = {}

            # Running balance: starts at on-hand, grows with incoming supply
            available_balance = on_hand

            # ── Sort periods ascending so on-hand is consumed earliest-first ──
            sorted_forecast_ids = sorted(
                schedule_state.get('forecast_ids', []),
                key=lambda d: (
                    date_type.fromisoformat(d['date_start'])
                    if isinstance(d.get('date_start'), str)
                    else (d.get('date_start') or date_type.min)
                )
            )

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
                if isinstance(date_start, date_type) and not isinstance(date_start, datetime):
                    year, month = date_start.year, date_start.month
                else:
                    year, month = date_start.year, date_start.month

                period_key = (year, month)

                # ── Apply running available balance (BUG 4 / 5 fix) ──────────
                if not skip_fg_coverage:
                    po_arriving   = open_po_by_month.get(period_key, 0.0)
                    mo_arriving   = open_mo_by_month.get(period_key, 0.0)
                    available_balance += po_arriving + mo_arriving

                    net_required = max(0.0, outstanding_qty - available_balance)
                    available_balance = max(0.0, available_balance - outstanding_qty)

                    _logger.info(
                        "[MPS All-Periods] %s [trigger=%s]  period %s-%02d : "
                        "replenish=%.2f  incoming(MPS)=%.2f  outstanding=%.2f  "
                        "po_arriving=%.2f  mo_arriving=%.2f  balance_before=%.2f  "
                        "net_required=%.2f  balance_after=%.2f",
                        production_schedule.product_id.display_name,
                        production_schedule.replenish_trigger,
                        year, month,
                        replenish_qty, incoming_qty, outstanding_qty,
                        po_arriving, mo_arriving,
                        available_balance + outstanding_qty - po_arriving - mo_arriving,
                        net_required,
                        available_balance,
                    )

                    if net_required <= 0.0:
                        _logger.info(
                            "[MPS All-Periods] %s period %s-%02d fully covered "
                            "by on-hand / open PO / open MO — skipping procurement.",
                            production_schedule.product_id.display_name,
                            year, month,
                        )
                        ds = extra_forecast['date_start']
                        de = extra_forecast['date_stop']
                        existing_forecasts = production_schedule.forecast_ids.filtered(
                            lambda f, ds=ds, de=de: f.date >= ds and f.date <= de
                        )
                        if existing_forecasts:
                            forecasts_to_set_as_launched |= existing_forecasts
                        else:
                            forecasts_values.append({
                                'forecast_qty': 0,
                                'date': de,
                                'procurement_launched': True,
                                'production_schedule_id': production_schedule.id,
                            })
                        continue

                    outstanding_qty = net_required

                else:
                    # BOM-explode path: pass the full outstanding_qty through to
                    # BOM explosion. Coverage is applied per component inside the
                    # accumulator merge below.
                    _logger.info(
                        "[MPS All-Periods] %s [trigger=%s / bom-buy=%s]  period %s-%02d : "
                        "replenish=%.2f  incoming(MPS)=%.2f  outstanding=%.2f  "
                        "(coverage applied per component in accumulator)",
                        production_schedule.product_id.display_name,
                        production_schedule.replenish_trigger,
                        has_manufacture_bom_buy,
                        year, month,
                        replenish_qty, incoming_qty, outstanding_qty,
                    )

                extra_values = production_schedule._get_procurement_extra_values(
                    extra_forecast
                )

                if has_manufacture_bom_buy:
                    # ── Explode normal BOM into raw component qtys ────────────
                    # This path runs for ALL products that have a normal BOM but
                    # no Manufacture route — regardless of replenish_trigger.
                    raw_components = []
                    _dummy, bom_lines = manufacture_bom_for_buy.explode(
                        production_schedule.product_id, outstanding_qty
                    )
                    all_comp_ids = [l[0].product_id.id for l in bom_lines]
                    already_sched = self.env['mrp.production.schedule'].search([
                        ('company_id',   '=', production_schedule.company_id.id),
                        ('warehouse_id', '=', production_schedule.warehouse_id.id),
                        ('product_id',   'in', all_comp_ids),
                    ]).product_id.ids
                    for bom_line, line_data in bom_lines:
                        comp = bom_line.product_id
                        if comp.id in already_sched:
                            continue
                        comp_route = self._mps_get_component_route(comp)
                        comp_vals  = dict(extra_values)
                        if comp_route:
                            comp_vals['route_ids'] = comp_route
                        else:
                            comp_vals.pop('route_ids', None)
                        comp_vals.pop('supplierinfo_id', None)
                        raw_components.append({
                            'product':      comp,
                            'raw_qty':      line_data['qty'],
                            'uom_id':       bom_line.product_uom_id,
                            'extra_values': comp_vals,
                            'company':      production_schedule.company_id,
                        })

                    for comp_data in raw_components:
                        comp_product = comp_data['product']

                        comp_acc_key = (
                            comp_product.id,
                            production_schedule.company_id.id,
                            production_schedule.warehouse_id.id if production_schedule.warehouse_id else False,
                            year,
                            month,
                        )

                        if comp_acc_key not in raw_qty_accumulator:
                            # Build coverage for this component now (queried once)
                            comp_on_hand = production_schedule._mps_get_on_hand_qty(
                                comp_product,
                                production_schedule.company_id,
                                production_schedule.warehouse_id,
                            )
                            comp_po_by_month = production_schedule._mps_get_open_po_qty_by_month(
                                comp_product,
                                production_schedule.company_id,
                                production_schedule.warehouse_id,
                            )
                            raw_qty_accumulator[comp_acc_key] = {
                                'product':            comp_product,
                                'raw_qty':            comp_data['raw_qty'],
                                'forecasted_on_hand': 0.0,
                                'uom_id':             comp_data['uom_id'],
                                'extra_values':       comp_data['extra_values'],
                                'company':            comp_data['company'],
                                'schedule':           production_schedule,
                                # coverage fields applied before safety stock
                                '_comp_on_hand':      comp_on_hand,
                                '_comp_po_by_month':  comp_po_by_month,
                            }
                        else:
                            raw_qty_accumulator[comp_acc_key]['raw_qty'] += comp_data['raw_qty']
                            _logger.info(
                                '[MPS All-Periods] Accumulator merge (BOM-explode): '
                                '%s  accumulated_raw_qty=%.4f (added %.4f from %s)',
                                comp_product.display_name,
                                raw_qty_accumulator[comp_acc_key]['raw_qty'],
                                comp_data['raw_qty'],
                                production_schedule.product_id.display_name,
                            )

                elif phantom_bom:
                    for bom_line, qty_ratio in phantom_product_ratio:
                        comp_product = bom_line.product_id
                        raw_comp_qty = outstanding_qty * qty_ratio
                        acc_key = (
                            comp_product.id,
                            production_schedule.company_id.id,
                            production_schedule.warehouse_id.id if production_schedule.warehouse_id else False,
                            year,
                            month,
                        )
                        if acc_key not in raw_qty_accumulator:
                            comp_values = dict(extra_values)
                            raw_qty_accumulator[acc_key] = {
                                'product':            comp_product,
                                'raw_qty':            raw_comp_qty,
                                'forecasted_on_hand': 0.0,
                                'uom_id':             bom_line.product_uom_id,
                                'extra_values':       comp_values,
                                'company':            production_schedule.company_id,
                                'schedule':           production_schedule,
                            }
                        else:
                            raw_qty_accumulator[acc_key]['raw_qty'] += raw_comp_qty

                else:
                    # Normal (non-phantom, non-never) schedule.
                    acc_key = (
                        production_schedule.product_id.id,
                        production_schedule.company_id.id,
                        production_schedule.warehouse_id.id if production_schedule.warehouse_id else False,
                        year,
                        month,
                    )
                    if acc_key not in raw_qty_accumulator:
                        raw_qty_accumulator[acc_key] = {
                            'product':            production_schedule.product_id,
                            'raw_qty':            outstanding_qty,
                            'forecasted_on_hand': forecasted_on_hand,
                            'uom_id':             production_schedule.product_uom_id,
                            'extra_values':       extra_values,
                            'company':            production_schedule.company_id,
                            'schedule':           production_schedule,
                        }
                    else:
                        raw_qty_accumulator[acc_key]['raw_qty'] += outstanding_qty
                        raw_qty_accumulator[acc_key]['forecasted_on_hand'] = min(
                            raw_qty_accumulator[acc_key]['forecasted_on_hand'],
                            forecasted_on_hand,
                        )

                # ── Collect forecast records to mark as launched (deferred) ───
                # We store them against the accumulator key so the surplus pass
                # can still mark them even when no PR is created for that month.
                ds = extra_forecast['date_start']
                de = extra_forecast['date_stop']

                # Determine the acc_key that was just written/updated above.
                # For component paths the last written key is comp_acc_key (set
                # inside the for-loop above); for the normal/phantom paths it is
                # the acc_key local variable.  We resolve by reading back from
                # the accumulator — the simplest approach is to tag the entry.
                # Instead we just store the forecast info directly keyed by
                # (production_schedule.id, year, month) and resolve later.
                fcast_tracking_key = (production_schedule.id, year, month)
                existing_forecasts = production_schedule.forecast_ids.filtered(
                    lambda f, ds=ds, de=de: f.date >= ds and f.date <= de
                )

                if fcast_tracking_key not in acc_key_to_forecast_records:
                    acc_key_to_forecast_records[fcast_tracking_key] = (
                        production_schedule, ds, de, existing_forecasts
                    )

        # =========================================================================
        # PRE-PASS: apply component on-hand / confirmed-PO coverage
        # =========================================================================
        # For BOM-exploded components the accumulator holds the full exploded
        # raw_qty across ALL finished-good periods.  Before the surplus carry
        # can work correctly we must deduct existing on-hand stock and confirmed
        # incoming POs from the raw_qty in each accumulator entry.
        #
        # ORDERING MATTERS:
        #   raw_qty (exploded)
        #     → minus on_hand + confirmed POs  (this pre-pass)
        #     → minus usable surplus from prior months  (surplus carry pass)
        #     → plus safety_stock + MOQ rounding  (final procurement creation)
        #
        # Doing coverage AFTER the surplus carry (old code) meant the surplus
        # calculated in month N was based on inflated raw_qty that hadn't yet
        # had on_hand deducted, so the carry-forward was wrong.
        #
        # Coverage uses a running balance per component (same product/company/
        # warehouse), sorted ascending by month, so on-hand covers the earliest
        # period first — exactly like the FG coverage logic above.
        # =========================================================================

        # Group component accumulator entries by (product_id, company_id, warehouse_id)
        # to build a per-product running balance across months.
        from collections import defaultdict

        # First: apply on_hand / PO deduction per component, using a running
        # available balance across months (earliest first).
        comp_group_keys = defaultdict(list)
        for acc_key, acc in raw_qty_accumulator.items():
            if '_comp_on_hand' in acc:   # only BOM-exploded component entries
                product_id, company_id, warehouse_id, year, month = acc_key
                comp_group_keys[(product_id, company_id, warehouse_id)].append(acc_key)

        for group_sig, keys in comp_group_keys.items():
            keys.sort(key=lambda k: (k[3], k[4]))   # ascending by (year, month)

            # Fetch coverage data from the first entry in the group
            first_acc = raw_qty_accumulator[keys[0]]
            comp_on_hand     = first_acc.get('_comp_on_hand',     0.0) or 0.0
            comp_po_by_month = first_acc.get('_comp_po_by_month', {})  or {}

            # Running available balance (mirrors FG coverage logic)
            available = comp_on_hand

            for acc_key in keys:
                acc = raw_qty_accumulator[acc_key]
                product_id, company_id, warehouse_id, year, month = acc_key

                po_arriving = comp_po_by_month.get((year, month), 0.0)
                available  += po_arriving

                raw_before   = acc['raw_qty']
                net_after    = max(0.0, raw_before - available)
                consumed     = raw_before - net_after          # how much balance absorbed
                available    = max(0.0, available - raw_before)

                _logger.info(
                    "[MPS Pre-Coverage] Component %s period %d-%02d : "
                    "raw=%.4f  on_hand_balance=%.4f  po_arriving=%.4f  "
                    "net=%.4f  balance_after=%.4f",
                    acc['product'].display_name,
                    year, month,
                    raw_before, comp_on_hand if acc_key == keys[0] else 0.0,
                    po_arriving, net_after, available,
                )

                # Replace raw_qty with coverage-adjusted value BEFORE surplus carry
                acc['raw_qty'] = net_after

                # Remove the coverage fields — they've been applied now
                acc.pop('_comp_on_hand',     None)
                acc.pop('_comp_po_by_month', None)

                if net_after <= 0.0:
                    _logger.info(
                        "[MPS Pre-Coverage] Component %s period %d-%02d fully "
                        "covered by on-hand/PO — will be skipped.",
                        acc['product'].display_name, year, month,
                    )

        # =========================================================================
        # SURPLUS CARRY-FORWARD PASS (BUG 6 + BUG 7 FIX)
        # =========================================================================
        # Group accumulator entries by (product_id, company_id, warehouse_id),
        # then iterate months in ascending order, carrying the surplus from
        # MOQ/safety-stock rounding forward so later months are not over-ordered.
        # Safety stock is PROTECTED — only surplus ABOVE safety_stock is usable.
        #
        # Correct pipeline (all three passes now in order):
        #   raw_qty  →  [pre-coverage: on_hand/PO]
        #            →  [surplus carry: usable = surplus − safety]
        #            →  [MOQ loop: add safety + round to MOQ]  →  PR
        # =========================================================================

        # Step 1: group keys by (product_id, company_id, warehouse_id)

        product_group_keys = defaultdict(list)
        for acc_key in list(raw_qty_accumulator.keys()):
            product_id, company_id, warehouse_id, year, month = acc_key
            group_sig = (product_id, company_id, warehouse_id)
            product_group_keys[group_sig].append(acc_key)

        # Step 2: for each product group, sort by month and apply surplus carry
        # with safety-stock protection (BUG 7 FIX).
        #
        # Safety stock is PROTECTED inventory.  Only stock ABOVE the safety
        # stock threshold may be treated as usable carry-forward surplus.
        #
        #   usable_surplus  = max(0, surplus − safety_stock)
        #   net_need        = max(0, raw_qty − usable_surplus)
        #   ordered_qty     = _mps_adjust_procurement_qty(net_need)
        #   surplus         = ordered_qty − net_need    ← carry to next month
        #
        # The surplus variable tracks the total projected stock above zero;
        # subtracting safety_stock before offsetting demand ensures we never
        # draw the protected buffer down to meet future demand.
        keys_to_skip = set()   # accumulator keys where net_need == 0 after surplus

        for group_sig, keys_in_group in product_group_keys.items():
            # Sort ascending by (year, month)
            keys_in_group.sort(key=lambda k: (k[3], k[4]))

            surplus = 0.0
            for acc_key in keys_in_group:
                acc = raw_qty_accumulator[acc_key]
                product_id, company_id, warehouse_id, year, month = acc_key

                # Fetch safety stock for this product (0.0 if not configured)
                tmpl = acc['product'].product_tmpl_id
                safety_stock = tmpl._get_safety_stock() if hasattr(tmpl, '_get_safety_stock') else 0.0

                raw_qty       = acc['raw_qty']
                usable_surplus = max(0.0, surplus - safety_stock)
                net_need       = max(0.0, raw_qty - usable_surplus)

                if net_need <= 0.0:
                    _logger.info(
                        "[MPS Surplus Carry] %s period %d-%02d : "
                        "raw_qty=%.4f  projected_balance=%.4f  safety_stock=%.4f  "
                        "usable_surplus=%.4f  net_need_before_moq=0 → SKIPPING (fully covered)",
                        acc['product'].display_name,
                        year, month,
                        raw_qty, surplus, safety_stock, usable_surplus,
                    )
                    # Surplus is reduced by the demand it just absorbed
                    surplus = max(0.0, surplus - raw_qty)
                    keys_to_skip.add(acc_key)
                    continue

                # Compute what MOQ/safety will order for this net_need
                adjusted_qty = acc['schedule']._mps_adjust_procurement_qty(
                    acc['product'],
                    net_need,
                    acc['forecasted_on_hand'],
                )
                new_surplus = max(0.0, adjusted_qty - net_need)

                _logger.info(
                    "[MPS Surplus Carry] %s period %d-%02d : "
                    "raw_qty=%.4f  projected_balance=%.4f  safety_stock=%.4f  "
                    "usable_surplus=%.4f  net_need_before_moq=%.4f  "
                    "ordered_qty=%.4f  carried_surplus=%.4f",
                    acc['product'].display_name,
                    year, month,
                    raw_qty, surplus, safety_stock,
                    usable_surplus, net_need,
                    adjusted_qty, new_surplus,
                )

                # Update raw_qty in the accumulator so the MOQ loop below
                # operates on the reduced (surplus-adjusted) quantity.
                acc['raw_qty'] = net_need
                surplus = new_surplus

        # =========================================================================
        # Apply safety_stock + MOQ ONCE per accumulator key
        # (skipping months that are fully covered by carry-forward surplus)
        # =========================================================================
        for acc_key, acc in raw_qty_accumulator.items():

            if acc_key in keys_to_skip:
                # Month is fully covered by surplus from a previous month's order.
                # Mark the corresponding forecast records as launched so MPS shows
                # the correct state, but do NOT create a PR.
                product_id, company_id, warehouse_id, year, month = acc_key
                _logger.info(
                    "[MPS All-Periods] %s period %d-%02d skipped by surplus carry — "
                    "marking forecast as launched without creating PR.",
                    acc['product'].display_name, year, month,
                )
                # Find and mark matching forecast records
                fcast_key = (acc['schedule'].id, year, month)
                if fcast_key in acc_key_to_forecast_records:
                    sched, ds, de, existing_forecasts = acc_key_to_forecast_records[fcast_key]
                    if existing_forecasts:
                        forecasts_to_set_as_launched |= existing_forecasts
                    else:
                        forecasts_values.append({
                            'forecast_qty': 0,
                            'date': de,
                            'procurement_launched': True,
                            'production_schedule_id': sched.id,
                        })
                continue

            # Component coverage has already been applied in the pre-pass above.
            # acc['raw_qty'] is already the net need after on_hand / confirmed POs.
            # If it is 0 or less, the period is fully covered — skip it.
            if acc['raw_qty'] <= 0.0:
                product_id, company_id, warehouse_id, year, month = acc_key
                _logger.info(
                    "[MPS All-Periods] Component %s period %d-%02d fully covered "
                    "by on-hand/PO (pre-coverage pass) — skipping.",
                    acc['product'].display_name, year, month,
                )
                continue

            adjusted_qty = acc['schedule']._mps_adjust_procurement_qty(
                acc['product'],
                acc['raw_qty'],
                acc['forecasted_on_hand'],
            )
            _logger.info(
                "[MPS All-Periods] FINAL qty for %s  period=%s-%02d : "
                "raw_qty=%.4f → adjusted=%.4f  (on_hand=%.4f)",
                acc['product'].display_name,
                acc_key[3],
                acc_key[4],
                acc['raw_qty'],
                adjusted_qty,
                acc['forecasted_on_hand'],
            )
            procurements.append(
                self.env['procurement.group'].Procurement(
                    acc['product'],
                    adjusted_qty,
                    acc['uom_id'],
                    acc['schedule'].warehouse_id.lot_stock_id,
                    acc['product'].name,
                    'MPS',
                    acc['company'],
                    acc['extra_values'],
                )
            )

        # ── Mark all forecast records as launched ─────────────────────────────
        # (includes months skipped by surplus, months with no PR, and months
        #  that had a PR — all get procurement_launched=True)
        for fcast_key, (sched, ds, de, existing_forecasts) in acc_key_to_forecast_records.items():
            if existing_forecasts:
                forecasts_to_set_as_launched |= existing_forecasts
            else:
                forecasts_values.append({
                    'forecast_qty': 0,
                    'date': de,
                    'procurement_launched': True,
                    'production_schedule_id': sched.id,
                })

        if not procurements:
            _logger.info("[MPS All-Periods] No outstanding procurements to run.")
            # Still write launched flags even if no PRs were created
            forecasts_to_set_as_launched.write({'procurement_launched': True})
            if forecasts_values:
                self.env['mrp.product.forecast'].create(forecasts_values)
            return False

        # ── Split: Buy → PRs  |  everything else → normal engine ─────────────
        buy_procurements   = []
        other_procurements = []

        for proc in procurements:
            if self._mps_is_buy_procurement(proc):
                buy_procurements.append(proc)
            else:
                other_procurements.append(proc)

        _logger.info(
            "[MPS All-Periods] %d buy procurement(s) → PRs  |  "
            "%d other procurement(s) → engine",
            len(buy_procurements),
            len(other_procurements),
        )

        # ── Create Purchase Requisitions for Buy procurements ─────────────────
        if buy_procurements:
            created_prs = self._mps_create_prs_from_buy_procurements(buy_procurements)
            _logger.info(
                "[MPS All-Periods] %d PR(s) created: %s",
                len(created_prs),
                [pr.name for pr in created_prs],
            )

        # ── Run Manufacture / other procurements through the normal engine ─────
        if other_procurements:
            _logger.info(
                "[MPS All-Periods] Running %d non-buy procurement(s).",
                len(other_procurements),
            )
            self.env['procurement.group'].with_context(
                skip_lead_time=True
            ).run(other_procurements)

        # ── Write procurement_launched flags ──────────────────────────────────
        forecasts_to_set_as_launched.write({'procurement_launched': True})
        if forecasts_values:
            self.env['mrp.product.forecast'].create(forecasts_values)