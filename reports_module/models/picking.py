from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # New fields based on the ZAFAR picking list
    driver_name = fields.Char(string="Driver No")
    truck_no = fields.Char(string="Truck No")
    delivery_via = fields.Char(string="Delivery Via")
    builty_no = fields.Char(string="Builty No")
    seal_no = fields.Char(string="Seal No")
    x_deliver_to_id = fields.Many2one('res.partner', string="Deliver To")

    # Storage location 3151 mapping
    storage_location_code = fields.Char(string="Storage Location", default="3151")


class StockMove(models.Model):
    _inherit = 'stock.move'

    # Breakdown quantities for the table
    qty_pak = fields.Float(string="Qty (PAK)", compute="_compute_breakdown_qtys")
    qty_ctn = fields.Float(string="Qty (CTN)", compute="_compute_breakdown_qtys")
    qty_pcs = fields.Float(string="Qty (PCS)", compute="_compute_breakdown_qtys")

    @api.depends('product_uom_qty', 'product_id')
    def _compute_breakdown_qtys(self):
        for move in self:
            # In a real scenario, these would calculate based on packaging rules.
            # Here we initialize them to match your document structure.
            move.qty_pak = move.product_uom_qty
            move.qty_ctn = move.product_uom_qty / 8.0  # Example ratio
            move.qty_pcs = move.product_uom_qty * 50.0  # Example ratio