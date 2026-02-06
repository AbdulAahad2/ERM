from odoo import api, fields, models

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    unit_cost = fields.Float(
        string="Unit Cost",
        compute='_compute_unit_cost',
        readonly=True,
        store=True,
    )
    total_valuation = fields.Float(
        string="Total Valuation",
        compute='_compute_total_valuation',
        readonly=True,
        store=True,
    )

    @api.depends('product_id', 'move_id.purchase_line_id.price_unit', 'qty_done')
    def _compute_unit_cost(self):
        for line in self:
            # 1. Fallback: If no product or quantity, cost is 0
            if not line.product_id or line.qty_done <= 0:
                line.unit_cost = 0.0
                continue

            # 2. Try to get price from the linked Purchase Order Line
            # We access this via the move_id
            po_line = line.move_id.purchase_line_id

            if po_line:
                # We use price_unit from the PO
                # Note: You might want to consider taxes or currency conversions here
                # depending on your accounting requirements.
                line.unit_cost = po_line.price_unit
            else:
                # 3. Fallback to Product standard_price if not a PO receipt
                line.unit_cost = line.product_id.standard_price

    @api.depends('unit_cost', 'qty_done')
    def _compute_total_valuation(self):
        for line in self:
            line.total_valuation = line.unit_cost * line.qty_done