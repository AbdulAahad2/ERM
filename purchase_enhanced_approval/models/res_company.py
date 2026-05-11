# Create or add to models/res_company.py
from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    default_pricing_procedure_id = fields.Many2one(
        'pricing.procedure',
        string="Default SAP Pricing Procedure"
    )