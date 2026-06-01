# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Add the missing field as a related field from the sale order line
    x_delivered_packaging_qty = fields.Float(
        string='Delivered Pkg',
        related='sale_line_ids.x_delivered_packaging_qty',
        digits='Product Unit of Measure',
        store=False,
        readonly=True
    )

    @api.onchange('quantity', 'product_packaging_id')
    def _onchange_quantity_sync_invoice_packs(self):
        """Automatically re-calculate package count when quantity is pulled into the invoice."""
        if self.product_packaging_id and self.product_packaging_id.qty:
            self.x_packaging_qty = self.quantity / self.product_packaging_id.qty