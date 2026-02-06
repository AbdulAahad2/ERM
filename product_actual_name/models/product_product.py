# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ProductProduct(models.Model):
    _inherit = 'product.product'

    # Computed field that gets actual_name from template
    actual_name = fields.Char(
        string='Actual Name',
        compute='_compute_actual_name',
        search='_search_actual_name',
        help='The actual name from product template'
    )

    @api.depends('product_tmpl_id.actual_name')
    def _compute_actual_name(self):
        """Get actual_name from the product template"""
        for product in self:
            product.actual_name = product.product_tmpl_id.actual_name

    def _search_actual_name(self, operator, value):
        """Allow searching by actual_name"""
        return [('product_tmpl_id.actual_name', operator, value)]

    @api.depends('name', 'default_code', 'product_tmpl_id.actual_name')
    def _compute_display_name(self):
        """Override display name to show actual_name when context flag is set"""
        for product in self:
            # Get actual_name from template
            actual_name = product.product_tmpl_id.actual_name

            if self._context.get('show_actual_name') and actual_name:
                # Use actual_name when the context flag is set
                name = actual_name
            else:
                # Use the regular name
                name = product.name

            # Add default_code prefix if it exists
            if product.default_code:
                name = f'[{product.default_code}] {name}'

            # Add variant info if this is a variant
            variant = product.product_template_variant_value_ids._get_combination_name()
            if variant:
                name = f"{name} ({variant})"

            product.display_name = name

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = list(args or [])

        # ONLY search actual_name if specifically requested via context
        if name and self._context.get('show_actual_name'):
            domain = [
                '|', '|', '|',
                ('name', operator, name),
                ('default_code', operator, name),
                ('product_tmpl_id.actual_name', operator, name),
                ('barcode', operator, name)
            ]
            args = domain + args
            products = self.search(args, limit=limit)
            return [(product.id, product.display_name) for product in products]

        # Default Odoo behavior for BoM and other modules
        return super(ProductProduct, self).name_search(name, args, operator, limit)