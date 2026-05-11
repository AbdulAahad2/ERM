from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mrp_price = fields.Float(
        string='MRP (Maximum Retail Price)',
        digits='Product Price',
        help='Maximum Retail Price used as base for tax calculation'
    )

    standard_cost = fields.Float(
        string='Standard Cost',
        digits='Product Price',
        help='Optional cost field for margin calculations'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'mrp_price' in vals and vals['mrp_price'] > 0:
                if 'list_price' not in vals or not vals['list_price']:
                    vals['list_price'] = vals['mrp_price']
        return super(ProductTemplate, self).create(vals_list)

    def write(self, vals):
        if 'mrp_price' in vals:
            for product in self:
                if product.mrp_price != vals.get('mrp_price'):
                    # Update list_price if it was equal to old MRP
                    if product.list_price == product.mrp_price:
                        vals['list_price'] = vals['mrp_price']
        return super(ProductTemplate, self).write(vals)