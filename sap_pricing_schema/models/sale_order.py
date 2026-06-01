from odoo import models, fields, api
from odoo.fields import Date
import logging
import traceback

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pricing_schema_id = fields.Many2one(
        'pricing.schema',
        string='Pricing Schema',
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
        string='Schema Date',
        default=fields.Date.today,
        help='Leave blank to use the order date for schema selection.\n'
             'For customer returns, enter the original sale date here — the system '
             'will automatically find and apply the pricing schema that was active '
             'on that date, giving the customer the same prices they were originally charged.'
    )
    effective_pricing_date = fields.Date(
        string='Effective Pricing Date',
        compute='_compute_effective_pricing_date',
        store=True,
        help='Resolved date used for schema validity lookup: Pricing Date if set, '
             'otherwise the Order Date, falling back to today. '
             'Referenced by the Pricing Schema domain to show only date-valid schemas.',
    )

    def _get_effective_pricing_date(self):
        self.ensure_one()
        if self.pricing_date:
            return self.pricing_date
        if self.date_order:
            date = self.date_order
            if hasattr(date, 'date'):
                return date.date()
            return date
        return Date.today()

    @api.depends('pricing_date', 'date_order')
    def _compute_effective_pricing_date(self):
        """Stored copy of _get_effective_pricing_date() so it can be used in XML view domains."""
        for order in self:
            order.effective_pricing_date = order._get_effective_pricing_date()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # REMOVE the date_from block entirely — sale.order has no date_from
            use_sap = vals.get('use_sap_pricing', True)
            if vals.get('partner_id') and use_sap and not vals.get('pricing_schema_id'):
                order_date = (
                    vals.get('pricing_date')
                    or vals.get('date_order')
                    or Date.today()
                )
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
        reapply_triggers = {'partner_id', 'date_order', 'pricing_date'}
    
        if reapply_triggers & set(vals):
            result = super().write(vals)
    
            for order in self:
                if not order.use_sap_pricing:
                    continue
    
                pricing_date = vals.get('pricing_date', order.pricing_date)
                date_order = vals.get('date_order', order.date_order)
                partner_id = vals.get('partner_id', order.partner_id.id)
    
                if pricing_date:
                    check_date = pricing_date
                elif date_order:
                    check_date = date_order.date() if hasattr(date_order, 'date') else date_order
                else:
                    check_date = Date.today()
    
                header_schema = self.env['pricing.schema'].get_matching_schema(
                    partner_id,
                    False,
                    order_date=check_date,
                    header_only=True,
                )
                new_header_id = header_schema.id if header_schema else None
    
                # Direct SQL — avoids ORM triggering pricing.schema constraints
                self.env.cr.execute(
                    "UPDATE sale_order SET pricing_schema_id = %s WHERE id = %s",
                    (new_header_id, order.id)
                )
                order.invalidate_recordset(['pricing_schema_id'])
    
                for line in order.order_line:
                    if not line.product_id:
                        continue
    
                    line_schema = self.env['pricing.schema'].get_matching_schema(
                        order.partner_id.id,
                        line.product_id.id,
                        template_code=None,
                        order_date=check_date,
                    )
                    new_schema = line_schema or order.pricing_schema_id
                    if not new_schema:
                        continue
    
                    line_write_vals = {'pricing_schema_id': new_schema.id}
                    if not line.mrp_price and line.product_id:
                        mrp = (
                            line.product_id.product_tmpl_id.mrp_price
                            or line.product_id.lst_price
                        )
                        if mrp:
                            line_write_vals['mrp_price'] = mrp
                    line.write(line_write_vals)
    
                    if line.pricing_schema_id and line.mrp_price:
                        line._apply_pricing_schema(save_breakdown=False)
    
            return result
    
        # Case 2: schema changed manually
        result = super().write(vals)
    
        if 'pricing_schema_id' in vals:
            for order in self:
                if not order.use_sap_pricing or not order.pricing_schema_id:
                    continue
                for line in order.order_line:
                    if not line.product_id:
                        continue
                    line_schema = self.env['pricing.schema'].get_matching_schema(
                        order.partner_id.id,
                        line.product_id.id,
                        template_code=None,
                        order_date=order._get_effective_pricing_date(),
                    )
                    new_schema = line_schema or order.pricing_schema_id
                    if not new_schema:
                        continue
                    line_write_vals = {'pricing_schema_id': new_schema.id}
                    if not line.mrp_price and line.product_id:
                        mrp = (
                            line.product_id.product_tmpl_id.mrp_price
                            or line.product_id.lst_price
                        )
                        if mrp:
                            line_write_vals['mrp_price'] = mrp
                    line.write(line_write_vals)
                    if line.pricing_schema_id and line.mrp_price:
                        line._apply_pricing_schema(save_breakdown=False)

                    for record in self:
                        if not record.date_from and not vals.get('date_from'):
                            _logger.error("pricing.schema WRITE on record %s with no date_from! vals=%s Traceback:\n%s",
                                          record.id, vals, ''.join(traceback.format_stack()))
    
        return result

    def action_view_pricing_breakdown(self):
        self.ensure_one()

    @api.onchange('partner_id', 'use_sap_pricing', 'pricing_date', 'date_order')
    def _onchange_partner_or_pricing(self):
        self._compute_effective_pricing_date()

        if not (self.partner_id and self.use_sap_pricing):
            self.pricing_schema_id = False
            return

        schema = self.env['pricing.schema'].get_matching_schema(
            self.partner_id.id,
            False,
            order_date=self._get_effective_pricing_date(),
            header_only=True,
        )
        self.pricing_schema_id = schema.id if schema else False

        for line in self.order_line:
            if not line.product_id:
                continue

            line_schema = self.env['pricing.schema'].get_matching_schema(
                self.partner_id.id,
                line.product_id.id,
                template_code=None,
                order_date=self._get_effective_pricing_date(),
            )
            line.pricing_schema_id = line_schema or self.pricing_schema_id

            if not line.mrp_price and line.product_id:
                line.mrp_price = (
                    line.product_id.mrp_price or line.product_id.lst_price
                )
            if line.pricing_schema_id and line.mrp_price:
                line._apply_pricing_schema(save_breakdown=False)

    def action_confirm(self):
        for order in self:
            if order.use_sap_pricing:
                for line in order.order_line:
                    if not line.pricing_schema_id:
                        schema = self.env['pricing.schema'].get_matching_schema(
                            order.partner_id.id,
                            line.product_id.id if line.product_id else False,
                            order_date=order._get_effective_pricing_date(),
                        )
                        if schema:
                            line.write({'pricing_schema_id': schema.id})
                        elif order.pricing_schema_id:
                            line.write({'pricing_schema_id': order.pricing_schema_id.id})

                    if not line.mrp_price and line.product_id:
                        mrp = line.product_id.mrp_price or line.product_id.lst_price
                        if mrp:
                            line.write({'mrp_price': mrp})
                    line._apply_pricing_schema(save_breakdown=True)
        return super().action_confirm()

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for move in moves:
            if any(l.sale_line_ids.order_id.use_sap_pricing for l in move.invoice_line_ids):
                move.use_sap_pricing = True
        return moves
