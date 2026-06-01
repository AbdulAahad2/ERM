from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    sap_tax_total = fields.Monetary(
        string='Total Odoo Tax',
        compute='_compute_sap_totals',
        currency_field='currency_id',
        store=True,
    )
    use_sap_pricing = fields.Boolean(
        string='Uses Odoo Pricing',
        compute='_compute_use_sap_pricing',
        store=True,
    )

    @api.depends(
        'invoice_line_ids.sap_tax_amount',
        'invoice_line_ids.sap_pricing_quantity',
        'invoice_line_ids.quantity',
    )
    def _compute_sap_totals(self):
        for move in self:
            move.sap_tax_total = sum(
                line.sap_tax_amount * line._get_sap_pricing_quantity()
                for line in move.invoice_line_ids
            )

    @api.depends('invoice_line_ids.sale_line_ids')
    def _compute_use_sap_pricing(self):
        for move in self:
            move.use_sap_pricing = any(
                line.sale_line_ids.order_id.use_sap_pricing
                for line in move.invoice_line_ids if line.sale_line_ids
            )

    def button_draft(self):
        """Remove SAP GL lines when resetting to draft so they are regenerated cleanly on next post."""
        for move in self:
            move.line_ids.filtered(
                lambda l: '[Odoo]' in (l.name or '')  # Fix: was '' which always matched every line
            ).with_context(check_move_validity=False).unlink()
        return super().button_draft()

    def action_post(self):
        # Handle both customer invoices and customer credit notes
        sap_move_types = ('out_invoice', 'out_refund')
        for move in self:
            if move.move_type in sap_move_types and move.use_sap_pricing:
                # 1. PRE-CLEAN: Strip Odoo's default taxes so they don't interfere
                move.invoice_line_ids.write({'tax_ids': [(5, 0, 0)]})
                move.line_ids.filtered(lambda l: l.tax_line_id).with_context(
                    check_move_validity=False
                ).unlink()

                # 2. INJECT: Add custom SAP lines while still in DRAFT
                move._add_sap_pricing_gl_lines()

        # 3. POST: Let Odoo finalize the move
        return super(AccountMove, self).action_post()

    def _add_sap_pricing_gl_lines(self):
        self.ensure_one()

        # Determines whether all debits/credits should be flipped
        is_refund = self.move_type == 'out_refund'

        receivable_line = self.line_ids.filtered(
            lambda l: l.account_type == 'asset_receivable'
        )[:1]

        debit_by_condition = {}
        tax_by_condition = {}
        base_price_by_inv_line = {}
        new_line_vals = []

        # ── PASS 1: Collect amounts from pricing breakdown ──────────────────
        for inv_line in self.invoice_line_ids:
            sale_line = inv_line.sale_line_ids[:1]
            if not sale_line:
                _logger.warning("Line %s: No sale_line_ids found!", inv_line.id)
                continue

            breakdown_lines = self.env['pricing.breakdown.line'].search([
                ('order_line_id', '=', sale_line.id),
                ('is_statistical', '=', False),
            ])

            _logger.info("Line %s: Found %s breakdown rows", inv_line.id, len(breakdown_lines))

            best_base_price = 0.0
            found_pr00 = False
            found_any_base = False

            for b in breakdown_lines:
                raw_amt = abs(b.computed_amount) * inv_line._get_sap_pricing_quantity()
                b_ctype = (b.condition_type or '').strip().upper()

                # ── Priority 1: Explicit PR00 condition type ─────────────────
                if b.rule_type == 'base_price' and b_ctype == 'PR00':
                    best_base_price = raw_amt
                    found_pr00 = True
                    _logger.info(
                        "Line %s: Found PR00 Base Price row '%s': %s",
                        inv_line.id, b.name, raw_amt,
                    )

                # ── Priority 2: Any other base_price row (e.g. ZXXX/MRP) ─────
                elif b.rule_type == 'base_price' and not found_pr00 and not found_any_base:
                    best_base_price = raw_amt
                    found_any_base = True
                    _logger.info(
                        "Line %s: Found fallback Base Price row '%s' (CType=%s): %s",
                        inv_line.id, b.name, b_ctype, raw_amt,
                    )

                elif b.line_type == 'tax' and b.gl_account_id:
                    cond_type = b.condition_type or 'tax_other'
                    if cond_type not in tax_by_condition:
                        tax_by_condition[cond_type] = {
                            'amount': 0.0,
                            'account_id': b.gl_account_id.id,
                            'condition_type': b.condition_type,
                        }
                    tax_by_condition[cond_type]['amount'] += raw_amt

                elif b.rule_type == 'discount' and b.gl_account_id:
                    cond_type = b.condition_type or 'discount_other'
                    if cond_type not in debit_by_condition:
                        debit_by_condition[cond_type] = {
                            'amount': 0.0,
                            'account_id': b.gl_account_id.id,
                            'condition_type': b.condition_type,
                        }
                    debit_by_condition[cond_type]['amount'] += raw_amt

            if best_base_price > 0:
                base_price_by_inv_line[inv_line.id] = best_base_price

        # ── PASS 2: Update existing invoice/refund lines (revenue lines) ────
        #
        #   Invoice (out_invoice):  revenue line is a CREDIT
        #   Credit note (out_refund): revenue line is a DEBIT  ← flipped
        #
        total_base_amount = 0.0
        for inv_line in self.invoice_line_ids:
            base_amt = base_price_by_inv_line.get(inv_line.id)

            if base_amt is not None:
                qty = inv_line._get_sap_pricing_quantity() or 1.0
                computed_unit_price = base_amt / qty

                _logger.info(
                    "Setting Line %s: Unit Price %s (Total %s) [refund=%s]",
                    inv_line.id, computed_unit_price, base_amt, is_refund,
                )

                inv_line.with_context(
                    check_move_validity=False, skip_invoice_line_sync=True
                ).write({
                    'price_unit': computed_unit_price,
                    'tax_ids': [(5, 0, 0)],
                })

                # Flip debit/credit for credit notes
                if is_refund:
                    inv_line.write({'debit': base_amt, 'credit': 0.0})
                else:
                    inv_line.write({'credit': base_amt, 'debit': 0.0})

                total_base_amount += base_amt
            else:
                _logger.warning("No SAP Base Price for line %s, using Odoo default", inv_line.id)
                # Use whichever side Odoo already populated
                total_base_amount += inv_line.debit if is_refund else inv_line.credit

        # ── PASS 2b: Prepare Discount / Tax journal lines ───────────────────
        #
        #   Invoice:     discount → DEBIT  | tax → CREDIT
        #   Credit note: discount → CREDIT | tax → DEBIT   ← all flipped
        #
        for cond, info in debit_by_condition.items():
            new_line_vals.append((0, 0, {
                'name': f'[Odoo] {cond} Discount',
                'account_id': info['account_id'],
                'debit':  0.0             if is_refund else info['amount'],
                'credit': info['amount']  if is_refund else 0.0,
                'partner_id': self.partner_id.id,
            }))

        for cond, info in tax_by_condition.items():
            new_line_vals.append((0, 0, {
                'name': f'[Odoo] {cond} Tax',
                'account_id': info['account_id'],
                'debit':  info['amount'] if is_refund else 0.0,
                'credit': 0.0            if is_refund else info['amount'],
                'partner_id': self.partner_id.id,
            }))

        # ── PASS 3: Recalculate the AR/AP balance line ───────────────────────
        #
        #   Invoice:     AR is DEBIT  (customer owes us)
        #   Credit note: AR is CREDIT (we owe the customer)  ← flipped
        #
        total_new_debits  = sum(l[2]['debit']  for l in new_line_vals if l[0] == 0)
        total_new_credits = sum(l[2]['credit'] for l in new_line_vals if l[0] == 0)

        if is_refund:
            # Credit note: AR credit = base debits + new tax debits - discount credits
            new_ar_amount = total_base_amount + total_new_debits - total_new_credits
            if receivable_line:
                new_line_vals.append((1, receivable_line.id, {
                    'credit': new_ar_amount,
                    'debit':  0.0,
                }))
        else:
            # Invoice: AR debit = base credits + new tax credits - discount debits
            new_ar_amount = total_base_amount + total_new_credits - total_new_debits
            if receivable_line:
                new_line_vals.append((1, receivable_line.id, {
                    'debit':  new_ar_amount,
                    'credit': 0.0,
                }))

        self.with_context(
            check_move_validity=False, skip_invoice_line_sync=True
        ).write({'line_ids': new_line_vals})

    def _prepare_product_base_line_for_taxes_computation(self, product_line):
        res = super()._prepare_product_base_line_for_taxes_computation(product_line)
        if (
                self.is_invoice(include_receipts=True)
                and product_line.sale_line_ids[:1].product_packaging_id.is_sales_package
        ):
            res['quantity'] = product_line._get_sap_pricing_quantity()
        return res


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    mrp_price = fields.Float(string='MRP', digits='Product Price')
    pricing_schema_id = fields.Many2one('pricing.schema', string='Applied Schema')
    discount_amount = fields.Float(string='Discount Applied', digits='Product Price')
    margin_amount = fields.Float(string='Margin Applied', digits='Product Price')
    charge_amount = fields.Float(string='Charges Applied', digits='Product Price')
    tax_base_amount = fields.Float(string='Tax Base (MRP)', digits='Product Price')
    sap_tax_amount = fields.Float(
        string='Odoo Tax Amount (Unit)',
        digits='Product Price',
        help='Unit tax amount (per unit, not extended by qty)',
    )
    sap_pricing_quantity = fields.Float(
        string='Pricing Qty',
        digits='Product Unit of Measure',
        help='Quantity used for package-based SAP pricing.',
    )

    def _get_sap_pricing_quantity(self):
        self.ensure_one()
        return self.sap_pricing_quantity or self.quantity

    @api.depends(
        'quantity', 'discount', 'price_unit', 'tax_ids', 'currency_id',
        'sap_pricing_quantity',
    )
    def _compute_totals(self):
        return super()._compute_totals()
