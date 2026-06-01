# -*- coding: utf-8 -*-
from odoo import api, fields, models

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # --- Field for ORDERING (Must remain so the view doesn't crash) ---
    x_packaging_qty = fields.Float(
        string='Packaging Qty',
        digits='Product Unit of Measure',
        default=0.0,
        help="Number of packages ordered."
    )

    # --- New Field for DELIVERY (To track what happened in GRN/Delivery) ---
    x_delivered_packaging_qty = fields.Float(
        string='Delivered Pkg Count',
        compute='_compute_delivered_packaging_qty',
        digits='Product Unit of Measure',
        store=True,
        help="Number of packages actually delivered based on the stock move."
    )

    @api.depends('qty_delivered', 'product_packaging_id')
    def _compute_delivered_packaging_qty(self):
        for line in self:
            if line.product_packaging_id and line.product_packaging_id.qty > 0:
                line.x_delivered_packaging_qty = line.qty_delivered / line.product_packaging_id.qty
            else:
                line.x_delivered_packaging_qty = 0.0

    # --- Logic for handling the Ordering process ---
    def _prepare_procurement_values(self, group_id=False):
        res = super(SaleOrderLine, self)._prepare_procurement_values(group_id=group_id)
        res.update({'x_packaging_qty': self.x_packaging_qty})
        return res

    @api.onchange('product_packaging_id')
    def _onchange_product_packaging_id_sales(self):
        packaging = self.product_packaging_id
        if packaging and packaging.is_sales_package:
            self.product_uom_qty = packaging.qty
            self.x_packaging_qty = 1.0
        elif packaging and packaging.qty:
            self.x_packaging_qty = self.product_uom_qty / packaging.qty

    @api.onchange('x_packaging_qty')
    def _onchange_x_packaging_qty(self):
        if self.product_packaging_id and self.product_packaging_id.qty and self.x_packaging_qty:
            self.product_uom_qty = self.x_packaging_qty * self.product_packaging_id.qty

    @api.onchange('product_uom_qty')
    def _onchange_product_uom_qty_sync_packs(self):
        if self.product_packaging_id and self.product_packaging_id.qty:
            self.x_packaging_qty = self.product_uom_qty / self.product_packaging_id.qty

    @api.onchange('product_id')
    def _onchange_product_id_set_sales_packaging(self):
        if not self.product_id:
            self.x_packaging_qty = 0.0
            return
        sales_pkg = self.env['product.packaging'].search([
            ('product_id', '=', self.product_id.id),
            ('is_sales_package', '=', True),
        ], limit=1)
        if sales_pkg:
            self.product_packaging_id = sales_pkg
            self.product_uom_qty = sales_pkg.qty
            self.x_packaging_qty = 1.0