from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    lot_code = fields.Char(string='Lot Code', help='Code used for auto-generating lot numbers (e.g., AO for Anita Oliver).')