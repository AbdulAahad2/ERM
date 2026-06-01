from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    x_packaging_qty = fields.Float(
        string='Pkg Count',
        compute='_compute_packaging_qty',
        inverse='_inverse_packaging_qty',
        store=True,
    )

    @api.depends('quantity', 'product_packaging_id') # Changed from product_uom_qty
    def _compute_packaging_qty(self):
        for move in self:
            if move.product_packaging_id and move.product_packaging_id.qty > 0:
                # This calculates packs based on what is actually DONE
                move.x_packaging_qty = move.quantity / move.product_packaging_id.qty
            else:
                move.x_packaging_qty = 0.0

    def _inverse_packaging_qty(self):
        for move in self:
            if move.product_packaging_id and move.product_packaging_id.qty > 0:
                # This updates the DONE quantity, leaving the DEMAND (240) alone
                move.quantity = move.x_packaging_qty * move.product_packaging_id.qty