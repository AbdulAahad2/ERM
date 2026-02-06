from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    semi_finish_initial = fields.Char(
        string="Semi-Finish Initial",
        help="Initial used to generate Semi-Finish code (e.g. ABC)"
    )

    is_semi_product = fields.Boolean(
        string="Is Semi-Finished Product",
        help="Check if this product is a semi-finished item"
    )
    related_semi_product_id = fields.Many2one(
        'product.product',
        string="Related Semi-Finished Product",
        help="The semi-finished product linked to this finished product"
    )
