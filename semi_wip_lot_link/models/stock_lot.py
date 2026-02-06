from odoo import models, fields

class StockLot(models.Model):
    _inherit = "stock.lot"

    semi_sequence = fields.Char(
        string="Semi Sequence",
        readonly=True
    )

    lot_initial = fields.Char(
        string="Lot Initial",
        readonly=True
    )
