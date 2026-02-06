# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    actual_name = fields.Char(
        string='Actual Name',
        help='The actual name of the product (e.g., Cream)',
        translate=True,
        index=True
    )

    def name_get(self):
        """Override name_get to show actual_name when context flag is set"""
        result = []
        for record in self:
            # Check if we should show actual_name
            if self._context.get('show_actual_name') and record.actual_name:
                name = record.actual_name
            else:
                name = record.name

            # Add default_code if it exists
            if record.default_code:
                name = f'[{record.default_code}] {name}'

            result.append((record.id, name))
        return result

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = list(args or [])
        # ONLY include actual_name if the Purchase or GRN context is active
        if name and self._context.get('show_actual_name'):
            domain = [
                '|', '|', '|',
                ('name', operator, name),
                ('default_code', operator, name),
                ('actual_name', operator, name),
                ('barcode', operator, name)
            ]
            args = domain + args
            return self.search(args, limit=limit).name_get()

        # Standard Odoo behavior for Sales, BoM, and all other modules
        return super(ProductTemplate, self).name_search(name, args, operator, limit)


# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    # Make actual_name easily accessible on purchase order lines
    product_actual_name = fields.Char(
        related='product_id.actual_name',
        string='Product Actual Name',
        readonly=True,
        store=False
    )

    @api.onchange('product_id')
    def _onchange_product_id_set_actual_name_context(self):
        """Ensure actual_name context is set when product changes"""
        return {
            'context': {
                'show_actual_name': True
            }
        }

    @api.depends('name', 'product_id.default_code', 'product_actual_name')
    def _compute_display_name(self):
        """Override display name to show actual_name when context flag is set"""
        for line in self:
            # Get actual_name from the line's related field
            actual_name = line.product_actual_name

            if self._context.get('show_actual_name') and actual_name:
                # Use actual_name when the context flag is set
                name = actual_name
            else:
                # Use the regular name
                name = line.name

            # Add default_code prefix if it exists (from the product)
            default_code = line.product_id.default_code
            if default_code:
                name = f'[{default_code}] {name}'

            # Add variant info if this is a variant
            variant = line.product_id.product_template_variant_value_ids._get_combination_name()
            if variant:
                name = f"{name} ({variant})"

            line.display_name = name