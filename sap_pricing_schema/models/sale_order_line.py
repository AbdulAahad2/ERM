from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_round
import logging

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    pricing_breakdown_line_ids = fields.One2many(
        'pricing.breakdown.line',
        'order_line_id',
        string='Pricing Breakdown Lines'
    )

    # FIXED: All monetary fields now use digits=(16, 4) for 4 decimal places
    mrp_price = fields.Float(
        string='MRP',
        digits=(16, 4),
        help='Maximum Retail Price — base for tax calculation (SAP: PR00 / PVKP).'
    )
    pricing_schema_id = fields.Many2one(
        'pricing.schema',
        string='Applied Schema',
        help='Pricing schema (procedure) applied to this line.'
    )
    total_with_tax = fields.Float(
        string='Total (incl. Tax)',
        digits=(16, 4),
        compute='_compute_total_with_tax',
        store=False,
    )

    discount_amount = fields.Float(string='Discount Applied', digits=(16, 4), default=0.0)
    surcharge_amount = fields.Float(string='Surcharge Applied', digits=(16, 4), default=0.0)
    charge_amount = fields.Float(string='Charges Applied', digits=(16, 4), default=0.0)

    margin_amount = fields.Float(
        string='Margin Applied',
        digits=(16, 4),
        compute='_compute_margin_amount',
        store=False,
    )

    final_unit_price = fields.Float(
        string='Net Unit Price',
        digits=(16, 4),
        compute='_compute_final_unit_price',
        store=True,
        help='MRP after all discounts / surcharges / charges (before tax).'
    )
    tax_base_amount = fields.Float(
        string='Tax Base (MRP)',
        digits=(16, 4),
        compute='_compute_tax_base',
        store=True,
        help='In SAP-style pricing, tax is calculated on MRP, not on the net price.'
    )

    sap_tax_amount = fields.Float(
        string='SAP Tax Amount (Unit)',
        digits=(16, 4),
        default=0.0,
        help='Tax amount computed by the pricing schema on MRP base PER UNIT (not extended by qty).'
    )

    unit_price_with_tax = fields.Float(
        string='Unit Price (incl. Tax)',
        digits=(16, 4),
        compute='_compute_unit_price_with_tax',
        store=False,
        help='Unit price that customer pays: final_unit_price + sap_tax_amount'
    )

    tax_breakdown_summary = fields.Text(
        string='Tax Breakdown',
        compute='_compute_tax_breakdown_summary',
        store=False,
        help='Summary of taxes applied from the pricing schema.'
    )

    source_template_id = fields.Many2one(
        'pricing.schema',
        string='Source Template',
        domain=[('is_template', '=', True)],
        help='Select a template to copy rules from.'
    )
    pricing_breakdown = fields.Text(
        string='Pricing Breakdown',
        compute='_compute_pricing_breakdown',
        store=False,
    )

    # ── ORM override: handle records created via import ──────────────────────
    @api.depends('surcharge_amount')
    def _compute_margin_amount(self):
        for line in self:
            line.margin_amount = line.surcharge_amount

    @api.depends('final_unit_price', 'sap_tax_amount')
    def _compute_unit_price_with_tax(self):
        """Compute the unit price with tax included for display purposes."""
        for line in self:
            if line.order_id.use_sap_pricing:
                line.unit_price_with_tax = line.final_unit_price + line.sap_tax_amount
            else:
                line.unit_price_with_tax = line.price_unit

    @api.depends('pricing_breakdown_line_ids.line_type', 'pricing_breakdown_line_ids.tax_amount',
                 'pricing_breakdown_line_ids.tax_id', 'pricing_breakdown_line_ids.applied_value')
    def _compute_tax_breakdown_summary(self):
        """Generate a summary of all taxes applied in this line (PER UNIT)."""
        for line in self:
            tax_lines = line.pricing_breakdown_line_ids.filtered(
                lambda b: b.line_type == 'tax'
            ).sorted('step')

            if not tax_lines:
                line.tax_breakdown_summary = False
                continue

            summary_parts = []
            total_tax_per_unit = 0.0
            for tax_b in tax_lines:
                tax_name = tax_b.tax_id.name if tax_b.tax_id else tax_b.name or 'Tax'
                tax_rate = tax_b.tax_id.amount if tax_b.tax_id else tax_b.applied_value
                rate_str = f"{tax_rate:.2f}%" if tax_rate else "—"

                summary_parts.append(
                    f"{tax_name}: {rate_str} = {tax_b.tax_amount:>10,.4f}"
                )
                total_tax_per_unit += tax_b.tax_amount

            if summary_parts:
                summary = "Taxes Applied (per unit):\n" + "\n".join(summary_parts)
                summary += f"\nTotal Tax (per unit): {total_tax_per_unit:>15,.4f}"
                line.tax_breakdown_summary = summary
            else:
                line.tax_breakdown_summary = False

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'sap_tax_amount')
    def _compute_amount(self):
        sap_lines = self.filtered(lambda l: l.order_id.use_sap_pricing)
        standard_lines = self - sap_lines

        # For standard lines, use Odoo's native calculation
        if standard_lines:
            super(SaleOrderLine, standard_lines)._compute_amount()

        # For SAP lines, also use Odoo's native calculation
        if sap_lines:
            super(SaleOrderLine, sap_lines)._compute_amount()

    @api.depends('mrp_price', 'discount_amount', 'surcharge_amount', 'charge_amount', 'price_unit')
    def _compute_final_unit_price(self):
        """
        CORRECTED: Calculate net unit price with proper SAP logic.

        SAP Rule:
        - Start with Base Price
        - Apply percentage discounts (e.g., 8% customer discount)
        - Apply additional charges (e.g., 10% material charge - SUBTRACTED)
        - Result = Net Unit Price (BEFORE tax)

        Prevent negative prices by flooring to 0.00.
        """
        for line in self:
            if line.order_id.use_sap_pricing and line.mrp_price:
                final_price = (
                        line.mrp_price
                        - line.discount_amount
                        + line.surcharge_amount
                        - line.charge_amount  # CORRECTED: Material charges are subtracted
                )

                if final_price < 0.0:
                    _logger.warning(
                        "[SAP Pricing] Order line %s: Negative price detected. "
                        "MRP: %.4f, Discounts: %.4f, Surcharges: %.4f, Charges: %.4f → Flooring to 0.00",
                        line.id, line.mrp_price, line.discount_amount,
                        line.surcharge_amount, line.charge_amount
                    )

                line.final_unit_price = max(0.0, final_price)
            else:
                line.final_unit_price = line.price_unit

    @api.depends('final_unit_price', 'sap_tax_amount')
    def _compute_total_with_tax(self):
        for line in self:
            if line.order_id.use_sap_pricing:
                line.total_with_tax = line.final_unit_price + line.sap_tax_amount
            else:
                line.total_with_tax = line.price_unit

    @api.depends('mrp_price', 'price_unit')
    def _compute_tax_base(self):
        """
        Derive tax base from the breakdown.
        In SAP, tax is calculated on the MRP base.
        """
        for line in self:
            if line.order_id.use_sap_pricing and line.pricing_breakdown_line_ids:
                tax_lines = line.pricing_breakdown_line_ids.filtered(
                    lambda b: b.line_type == 'tax'
                ).sorted('step')
                if tax_lines:
                    line.tax_base_amount = tax_lines[0].tax_base
                else:
                    line.tax_base_amount = line.mrp_price
            else:
                line.tax_base_amount = line.price_unit

    @api.depends(
        'mrp_price', 'discount_amount', 'surcharge_amount',
        'charge_amount', 'final_unit_price', 'tax_base_amount', 'sap_tax_amount', 'product_uom_qty',
        'pricing_breakdown_line_ids.line_type', 'pricing_breakdown_line_ids.computed_amount',
        'pricing_breakdown_line_ids.name', 'pricing_breakdown_line_ids.applied_value',
        'pricing_breakdown_line_ids.step', 'pricing_breakdown_line_ids.tax_amount',
        'pricing_breakdown_line_ids.tax_id', 'pricing_breakdown_line_ids.tax_base',
    )
    def _compute_pricing_breakdown(self):
        """
        Generate comprehensive pricing breakdown showing:
        - MRP base
        - Customer discount (8% on base price)
        - Material charge (10% on net price - subtracted)
        - Adjusted net price
        - Taxes on MRP
        - Final unit price (tax-inclusive)
        """
        for line in self:
            if not line.order_id.use_sap_pricing or not line.mrp_price:
                line.pricing_breakdown = False
                continue

            breakdown = (
                f"{'=' * 70}\n"
                f"SAP PRICING BREAKDOWN\n"
                f"{'=' * 70}\n\n"
                f"Quantity:                      {line.product_uom_qty:>12,.0f}\n"
                f"{'─' * 70}\n\n"
            )

            breakdown += f"MRP (Maximum Retail Price):  {line.mrp_price:>12,.4f}\n"

            condition_lines = line.pricing_breakdown_line_ids.filtered(
                lambda b: b.line_type == 'condition' and not b.is_statistical
            ).sorted('step')

            if condition_lines:
                breakdown += f"{'-' * 70}\n"
                breakdown += "ADJUSTMENTS:\n"
                for cond_b in condition_lines:
                    if cond_b.rule_type == 'discount':
                        sign = "−"
                        breakdown += f"  {sign} {cond_b.name[:40]:<40} {cond_b.computed_amount:>12,.4f}\n"
                    else:
                        sign = "−"  # Material charges are subtracted
                        breakdown += f"  {sign} {cond_b.name[:40]:<40} {cond_b.computed_amount:>12,.4f}\n"

            subtotal_lines = line.pricing_breakdown_line_ids.filtered(
                lambda b: b.line_type == 'subtotal'
            ).sorted('step')

            net_unit_price = line.final_unit_price
            if subtotal_lines:
                subtotal = subtotal_lines[0]
                breakdown += (
                    f"{'-' * 70}\n"
                    f"Net Unit Price (Subtotal):   {net_unit_price:>12,.4f}\n"
                )
                if subtotal.tax_base > 0:
                    breakdown += f"Tax Calculation Base (MRP):  {subtotal.tax_base:>12,.4f}\n"

            tax_lines = line.pricing_breakdown_line_ids.filtered(
                lambda b: b.line_type == 'tax'
            ).sorted('step')

            total_tax_per_unit = 0.0
            if tax_lines:
                breakdown += f"{'-' * 70}\n"
                breakdown += "TAXES (calculated on MRP, per unit):\n"
                for tax_b in tax_lines:
                    tax_name = tax_b.tax_id.name if tax_b.tax_id else tax_b.name or 'Tax'
                    tax_rate = tax_b.tax_id.amount if tax_b.tax_id else tax_b.applied_value
                    rate_str = f"{tax_rate:.2f}%" if tax_rate else "—"

                    breakdown += (
                        f"  {tax_name[:35]:<35} {rate_str:>5} = {tax_b.tax_amount:>10,.4f}\n"
                    )
                    total_tax_per_unit += tax_b.tax_amount

            unit_price_with_tax = net_unit_price + line.sap_tax_amount
            breakdown += f"{'-' * 70}\n"
            breakdown += f"Net Unit Price:              {net_unit_price:>12,.4f}\n"
            breakdown += f"Total Tax (per unit):        {line.sap_tax_amount:>12,.4f}\n"
            breakdown += f"{'=' * 70}\n"
            breakdown += f"Unit Price (incl. Tax):      {unit_price_with_tax:>12,.4f}\n"

            if line.product_uom_qty > 1:
                breakdown += f"{'─' * 70}\n"
                breakdown += f"EXTENDED AMOUNTS (Qty = {line.product_uom_qty}):\n"
                breakdown += f"{'─' * 70}\n"
                breakdown += f"Extended Net Amount:        {net_unit_price * line.product_uom_qty:>12,.4f}\n"
                breakdown += f"Extended Tax Amount:        {line.sap_tax_amount * line.product_uom_qty:>12,.4f}\n"
                breakdown += f"{'=' * 70}\n"
                breakdown += f"Extended Total (incl. Tax): {unit_price_with_tax * line.product_uom_qty:>12,.4f}\n"

            breakdown += f"{'=' * 70}\n"

            line.pricing_breakdown = breakdown

    def _apply_pricing_schema(self, save_breakdown=True):
        """
        FULLY CORRECTED SAP pricing waterfall.

        Key Fixes:
        1. Conditions modify current_price only (not display_running_total)
        2. Pre-tax subtotals checkpoint display_running_total to current_price
        3. Post-tax subtotals preserve display_running_total (don't reset)
        4. Taxes are added to display_running_total
        5. Only statistical rules are skipped
        """
        self.ensure_one()

        if not self.pricing_schema_id and self.order_id.pricing_schema_id:
            self.pricing_schema_id = self.order_id.pricing_schema_id

        if not self.pricing_schema_id or not self.mrp_price:
            _logger.warning("[SAP Pricing] Skipping line %s: Missing schema or MRP", self.id)
            return {}

        current_price = self.mrp_price
        display_running_total = self.mrp_price

        step_values = {}
        step_amounts = {}
        breakdown_vals = []

        total_discount = 0.0
        total_surcharge = 0.0
        total_charge = 0.0
        total_tax_amount = 0.0
        collected_tax_ids = []

        tax_base_for_breakdown = 0.0  # Track tax base for each tax step

        active_rules = self.pricing_schema_id.rule_ids.filtered(
            lambda r: r.active
        ).sorted(key=lambda r: (r.step, r.counter))

        for rule in active_rules:
            price_before = current_price

            # ===== FIX #2: Skip ONLY statistical rules =====
            if rule.is_statistical:
                _logger.debug(
                    "[SAP Pricing] Line %s: Skipping statistical rule '%s' at step %s",
                    self.id, rule.name, rule.step
                )
                breakdown_vals.append({
                    'order_line_id': False,
                    'step': rule.step,
                    'counter': rule.counter,
                    'condition_type': rule.condition_type or '---',
                    'name': rule.name,
                    'line_type': rule.line_type,
                    'rule_type': rule.rule_type,
                    'base_amount': current_price,
                    'applied_value': rule.value,
                    'computed_amount': 0.0,
                    'running_price': display_running_total,
                    'tax_base': 0.0,
                    'tax_amount': 0.0,
                    'tax_id': False,
                    'gl_account_id': False,
                    'account_key': '',
                    'is_statistical': True,
                })
                continue

            # Process all non-statistical rules
            # Determine tax input base: MRP (default SAP) or running net price (income/withholding tax)
            if rule.line_type == 'tax':
                if getattr(rule, 'tax_base_source', 'mrp') == 'running_price':
                    tax_input_base = current_price
                else:
                    tax_input_base = self.mrp_price
            else:
                tax_input_base = current_price

            result = rule.apply_rule(
                tax_input_base,
                quantity=self.product_uom_qty,
                step_values=step_values,
                step_amounts=step_amounts,
            )

            amount = result.get('amount', 0.0)
            new_price = result.get('new_price', current_price)
            tax_ids = result.get('tax_ids', [])
            tax_amount = result.get('tax_amount', 0.0)
            tax_base = result.get('tax_base', 0.0)

            _logger.info(
                "[SAP Debug] Step %s (%s): rule_type=%s, line_type=%s, "
                "current_price=%.4f, amount=%.4f, tax_amount=%.4f, new_price=%.4f",
                rule.step, rule.name, rule.rule_type, rule.line_type,
                current_price, amount, tax_amount, new_price
            )

            for tid in tax_ids:
                if tid not in collected_tax_ids:
                    collected_tax_ids.append(tid)

            if tax_amount:
                total_tax_amount += tax_amount

            # Aggregate discount/surcharge/charge
            if not rule.is_statistical and rule.line_type == 'condition':
                if rule.rule_type == 'discount':
                    total_discount += amount
                elif rule.rule_type == 'surcharge':
                    total_surcharge += amount
                elif rule.rule_type == 'charge':
                    total_charge += amount

            if not rule.is_statistical and rule.line_type != 'tax':
                current_price = new_price

            signed_amount = 0.0
            if rule.line_type == 'tax':
                signed_amount = tax_amount
            elif rule.line_type == 'subtotal':
                signed_amount = amount
            elif rule.line_type == 'condition':
                signed_amount = -amount if rule.rule_type == 'discount' else amount
                # ← UPDATE display_running_total so condition rows show correct running price
                display_running_total = current_price
            # ── Store step tracking dicts ─────────────────────────────────────
            # Subtotals MUST store display_running_total (which includes taxes
            # accumulated so far) so that any later rule referencing this step
            # (e.g. JEXT on step 80) receives the correct post-tax running price.
            # Conditions and taxes store their signed delta / tax_base as before.
            if rule.line_type == 'subtotal':
                step_values[rule.step] = display_running_total
                step_amounts[rule.step] = display_running_total   # range-sums also use running price for subtotals
            elif rule.line_type == 'tax':
                step_values[rule.step] = tax_base                 # base the tax was computed on
                step_amounts[rule.step] = signed_amount           # = tax_amount
            else:
                step_values[rule.step] = current_price
                step_amounts[rule.step] = signed_amount

            # ===== FINAL CORRECTED FIX #1 WITH SUBTOTAL HANDLING =====
            if not rule.is_statistical:
                if rule.line_type == 'tax':
                    # Store the base BEFORE adding tax
                    tax_base_for_breakdown = display_running_total

                    # Add tax to running total
                    display_running_total += tax_amount

                    _logger.debug(
                        "[SAP Pricing] Line %s Step %s (%s): Tax %.4f on base %.4f, "
                        "running_total now %.4f",
                        self.id, rule.step, rule.name, tax_amount, tax_base_for_breakdown, display_running_total
                    )

                elif rule.line_type == 'subtotal':
                    # CRITICAL FIX: Only reset if we haven't entered the tax section yet
                    # Once taxes are applied, subtotals should preserve the running_total
                    if total_tax_amount == 0.0:
                        # Pre-tax subtotal: checkpoint to current_price
                        display_running_total = current_price
                        _logger.debug(
                            "[SAP Pricing] Line %s Step %s (%s): Pre-tax subtotal checkpoint, "
                            "display_running_total = %.4f",
                            self.id, rule.step, rule.name, display_running_total
                        )
                    else:
                        # Post-tax subtotal: preserve running_total (which includes taxes)
                        _logger.debug(
                            "[SAP Pricing] Line %s Step %s (%s): Post-tax subtotal, "
                            "keeping running_total = %.4f",
                            self.id, rule.step, rule.name, display_running_total
                        )

                # Conditions (discount/surcharge/charge) do NOT directly affect display_running_total
                # They affect current_price, which is then captured by the next subtotal

            gl_account_id = False
            account_key = rule.account_key or ''
            if rule.account_id:
                gl_account_id = rule.account_id.id
            else:
                mapping = self.env['pricing.gl.mapping'].search([
                    ('company_id', '=', rule.company_id.id),
                    ('condition_type', '=', rule.condition_type),
                    ('rule_type', '=', rule.rule_type if rule.line_type != 'tax' else 'charge'),
                    ('active', '=', True),
                ], limit=1)
                if mapping:
                    gl_account_id = mapping.account_id.id
                    account_key = mapping.account_key or account_key

            if rule.line_type == 'subtotal':
                # Show the running price as the subtotal value (not 0); bold in the view
                display_computed = display_running_total
            elif rule.line_type == 'tax':
                display_computed = tax_amount
            else:
                display_computed = amount

            line_tax_id = False
            if rule.line_type == 'tax' and rule.tax_id:
                line_tax_id = rule.tax_id.id

            # ===== FIX #3: Corrected tax_base calculation - INCLUDES COUNTER FIELD =====
            breakdown_vals.append({
                'order_line_id': False,
                'step': rule.step,
                'condition_type': rule.condition_type or '---',
                'name': rule.name,
                'line_type': rule.line_type,
                'rule_type': rule.rule_type,
                'base_amount': price_before,
                'applied_value': rule.tax_id.amount if rule.line_type == 'tax' and rule.tax_id else rule.value,
                'computed_amount': display_computed,
                'running_price': display_running_total,  # ← Now correct!
                'tax_base': tax_base if rule.line_type == 'tax' else 0.0,
                'tax_amount': tax_amount if rule.line_type == 'tax' else 0.0,
                'tax_id': line_tax_id,
                'gl_account_id': gl_account_id,
                'account_key': account_key,
                'is_statistical': rule.is_statistical,
            })

        # Store price_unit as TAX-INCLUSIVE, sap_tax_amount as PER UNIT
        vals = {
            'price_unit': current_price + total_tax_amount,
            'discount_amount': total_discount,
            'surcharge_amount': total_surcharge,
            'charge_amount': total_charge,
            'sap_tax_amount': total_tax_amount,
        }

        if collected_tax_ids:
            vals['tax_id'] = [(6, 0, collected_tax_ids)]
        elif self.pricing_schema_id.default_tax_ids:
            vals['tax_id'] = [(6, 0, self.pricing_schema_id.default_tax_ids.ids)]
        else:
            vals['tax_id'] = [(5, 0, 0)]

        self.write(vals)

        if save_breakdown and isinstance(self.id, int) and breakdown_vals:
            self.env['pricing.breakdown.line'].search([('order_line_id', '=', self.id)]).unlink()
            for v in breakdown_vals:
                v['order_line_id'] = self.id
            self.env['pricing.breakdown.line'].create(breakdown_vals)

        _logger.info(
            "[SAP Pricing] Line %s: Final calculation complete. "
            "Net Price: %.4f, Discount: %.4f, Surcharge: %.4f, Charge: %.4f, Tax (per unit): %.4f, "
            "Tax-Inclusive Unit Price: %.4f",
            self.id, current_price, total_discount, total_surcharge, total_charge,
            total_tax_amount, current_price + total_tax_amount
        )

        return {
            'final_price': current_price,
            'final_price_with_tax': current_price + total_tax_amount,
            'breakdown_vals': breakdown_vals,
            'tax_ids': collected_tax_ids,
            'tax_amount': total_tax_amount,
        }

    @api.onchange('product_id', 'product_uom_qty', 'pricing_schema_id')
    def _onchange_sap_pricing_trigger(self):
        if not self.order_id.use_sap_pricing or not self.product_id:
            return

        if not self.mrp_price:
            mrp = (
                    self.product_id.product_tmpl_id.mrp_price
                    or self.product_id.lst_price
            )
            self.mrp_price = mrp
            if mrp and isinstance(self.id, int):
                self.write({'mrp_price': mrp})

        if not self.pricing_schema_id and self.order_id.pricing_schema_id:
            self.pricing_schema_id = self.order_id.pricing_schema_id

        if not self.pricing_schema_id:
            schema = self.env['pricing.schema'].get_matching_schema(
                self.order_id.partner_id.id,
                self.product_id.id,
                template_code=(
                    self.order_id.pricing_schema_id.code
                    if self.order_id.pricing_schema_id else None
                ),
                order_date=self.order_id.date_order,
            )
            if schema:
                self.pricing_schema_id = schema

        if self.pricing_schema_id and self.mrp_price:
            self._apply_pricing_schema(save_breakdown=False)

    @api.onchange('product_id', 'product_uom_qty', 'pricing_schema_id')
    def _onchange_product_pricing(self):
        """Recompute price_unit live on draft orders when product or qty changes."""
        order = self.order_id
        if not (order.use_sap_pricing and order.pricing_schema_id):
            return
        if not self.pricing_schema_id:
            self.pricing_schema_id = order.pricing_schema_id
        if not self.mrp_price and self.product_id:
            self.mrp_price = self.product_id.mrp_price or self.product_id.lst_price
        self._apply_pricing_schema(save_breakdown=False)

    def action_show_pricing_breakdown(self):
        self.ensure_one()

        if not self.pricing_schema_id and self.order_id.pricing_schema_id:
            self.pricing_schema_id = self.order_id.pricing_schema_id

        if not self.pricing_schema_id:
            raise UserError(_("No pricing schema is applied to this line."))

        active_rules = self.pricing_schema_id.rule_ids.filtered(lambda r: r.active)
        if not active_rules:
            raise UserError(_(
                "The pricing schema '%s' has no active rules. "
                "Please add pricing rules to this schema."
            ) % self.pricing_schema_id.name)

        if not isinstance(self.id, int):
            raise UserError(_("Please save the order before viewing the pricing breakdown."))

        if not self.mrp_price and self.product_id:
            mrp = (
                    self.product_id.product_tmpl_id.mrp_price
                    or self.product_id.lst_price
            )
            if mrp:
                self.write({'mrp_price': mrp})

        if not self.mrp_price:
            raise UserError(_("MRP is not set for this line. Please configure MRP on the product."))

        self._apply_pricing_schema(save_breakdown=True)

        count = self.env['pricing.breakdown.line'].search_count([
            ('order_line_id', '=', self.id)
        ])
        if not count:
            raise UserError(_("Failed to generate pricing breakdown lines."))

        return {
            'name': _('Pricing Breakdown: %s') % (self.product_id.display_name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'pricing.breakdown.line',
            'view_mode': 'list',
            'view_id': self.env.ref('sap_pricing_schema.view_pricing_breakdown_line_tree').id,
            'target': 'new',
            'domain': [('order_line_id', '=', self.id)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            order = line.order_id
            if not order.use_sap_pricing:
                continue

            # 1. Resolve schema — line may not have one yet if import omits it
            if not line.pricing_schema_id:
                schema = order.pricing_schema_id
                if not schema and order.partner_id:
                    # Header schema not set yet either — look it up directly
                    schema = self.env['pricing.schema'].get_matching_schema(
                        order.partner_id.id,
                        line.product_id.id if line.product_id else False,
                        order_date=order._get_effective_pricing_date(),
                        header_only=True,
                    )
                if schema:
                    line.write({'pricing_schema_id': schema.id})

            if not line.pricing_schema_id:
                continue  # Still no schema — nothing to apply

            # 2. Resolve MRP — importer only knows product, not MRP
            if not line.mrp_price and line.product_id:
                mrp = (
                        line.product_id.product_tmpl_id.mrp_price
                        or line.product_id.lst_price
                )
                if mrp:
                    line.write({'mrp_price': mrp})

            if not line.mrp_price:
                continue  # No MRP means no pricing possible

            # 3. Now safe to apply — both schema and MRP confirmed present
            line._apply_pricing_schema(save_breakdown=False)

        return lines

    def action_copy_from_template(self):
        """Copy all rules from the selected source_template_id to this line's schema."""
        self.ensure_one()
        if not self.source_template_id:
            raise UserError(_("Please select a Source Template first."))

        self.pricing_schema_id.rule_ids.unlink()
        for rule in self.source_template_id.rule_ids:
            rule.copy({
                'schema_id': self.pricing_schema_id.id,
                'company_id': self.order_id.company_id.id,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Rules copied from %s.') % self.source_template_id.name,
                'type': 'success',
                'sticky': False,
            }
        }

    def _prepare_invoice_line(self, **optional_values):
        res = super()._prepare_invoice_line(**optional_values)
        if self.order_id.use_sap_pricing:
            res.update({
                'mrp_price': self.mrp_price,
                'pricing_schema_id': self.pricing_schema_id.id,
                'sap_tax_amount': self.sap_tax_amount,
                'discount_amount': self.discount_amount,
                'charge_amount': self.charge_amount,
                'tax_base_amount': self.tax_base_amount,
            })
        return res