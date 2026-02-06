from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    requires_requisition = fields.Boolean(
        string="Requires Employee Requisition",
        help="If enabled, this product can only be requested via employee requisition."
    )
