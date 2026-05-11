from odoo import models, fields, api
from odoo.fields import Date
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pricing_schema_id = fields.Many2one(
        'pricing.schema',
        string='Pricing Schema',
        readonly=True,
        help='Selected pricing schema based on customer'
    )
    pricing_schema_name = fields.Char(
        related='pricing_schema_id.name',
        string='Schema Name',
        store=True
    )
    schema_template_code = fields.Char(
        string='Schema Template Code',
        related='pricing_schema_id.code',
        readonly=True,
        store=False
    )
    use_sap_pricing = fields.Boolean(
        string='Use SAP Pricing',
        default=True,
        help='Enable SAP-style pricing with MRP-based tax calculation'
    )
    pricing_date = fields.Date(
        string='Pricing Date (for Returns)',
        help='Leave blank to use the order date for schema selection.\n'
             'For customer returns, enter the original sale date here — the system '
             'will automatically find and apply the pricing schema that was active '
             'on that date, giving the customer the same prices they were originally charged.'
    )

    def _get_effective_pricing_date(self):
        """Return the date to use for schema validity lookup.
        For returns, this is pricing_date; otherwise the order date or today."""
        self.ensure_one()
        if self.pricing_date:
            return self.pricing_date
        if self.date_order:
            date = self.date_order
            if hasattr(date, 'date'):
                return date.date()
            return date

        return Date.today()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # use_sap_pricing defaults to True on the field — during import the key
            # is absent from vals, so we must fall back to True rather than treating
            # its absence as False.
            use_sap = vals.get('use_sap_pricing', True)
            if vals.get('partner_id') and use_sap and not vals.get('pricing_schema_id'):
                order_date = vals.get('pricing_date') or vals.get('date_order')
                schema = self.env['pricing.schema'].get_matching_schema(
                    vals['partner_id'],
                    False,
                    order_date=order_date,
                    header_only=True,
                )
                if schema:
                    vals['pricing_schema_id'] = schema.id
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if 'pricing_schema_id' in vals or 'partner_id' in vals:
            for order in self:
                if not order.use_sap_pricing or not order.pricing_schema_id:
                    continue

                for line in order.order_line:
                    write_vals = {}

                    # Push schema down if missing
                    if not line.pricing_schema_id:
                        write_vals['pricing_schema_id'] = order.pricing_schema_id.id

                    # Pull MRP from product if missing — importer won't supply this
                    if not line.mrp_price and line.product_id:
                        mrp = (
                                line.product_id.product_tmpl_id.mrp_price
                                or line.product_id.lst_price
                        )
                        if mrp:
                            write_vals['mrp_price'] = mrp

                    if write_vals:
                        line.write(write_vals)

                    # Now reprice — schema and MRP are guaranteed to be set
                    if line.pricing_schema_id and line.mrp_price:
                        line._apply_pricing_schema(save_breakdown=False)

        return result

    def action_view_pricing_breakdown(self):
        self.ensure_one()

    @api.onchange('partner_id', 'use_sap_pricing', 'pricing_date')
    def _onchange_partner_or_pricing(self):
        if self.partner_id and self.use_sap_pricing:
            schema = self.env['pricing.schema'].get_matching_schema(
                self.partner_id.id,
                False,
                order_date=self._get_effective_pricing_date(),
                header_only=True,
            )
            self.pricing_schema_id = schema.id if schema else False
        else:
            self.pricing_schema_id = False

        # ── NEW: reprice existing lines immediately, no reload needed ──
        if self.use_sap_pricing and self.pricing_schema_id:
            for line in self.order_line:
                if not line.pricing_schema_id:
                    line.pricing_schema_id = self.pricing_schema_id
                if not line.mrp_price and line.product_id:
                    line.mrp_price = (
                            line.product_id.mrp_price or line.product_id.lst_price
                    )
                line._apply_pricing_schema(save_breakdown=False)

    def action_confirm(self):
        for order in self:
            if order.use_sap_pricing:
                for line in order.order_line:
                    if not line.pricing_schema_id:
                        line.pricing_schema_id = order.pricing_schema_id
                    # Ensure MRP is persisted to DB before calculation.
                    # Setting line.mrp_price = X in memory is not enough —
                    # _apply_pricing_schema reads self.mrp_price from the ORM
                    # which needs a proper write() to be reliable.
                    if not line.mrp_price and line.product_id:
                        mrp = line.product_id.mrp_price or line.product_id.lst_price
                        if mrp:
                            line.write({'mrp_price': mrp})
                    line._apply_pricing_schema(save_breakdown=True)
        return super().action_confirm()

    # We remove the manual line.write loop in _create_invoices.
    # The logic is now handled automatically via SaleOrderLine._prepare_invoice_line
    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for move in moves:
            if any(l.sale_line_ids.order_id.use_sap_pricing for l in move.invoice_line_ids):
                move.use_sap_pricing = True
        return moves