# -*- coding: utf-8 -*-

from odoo import models, fields, api


class StockMove(models.Model):
    _inherit = 'stock.move'

    # Add actual_name as related field for easy access
    product_actual_name = fields.Char(
        related='product_id.actual_name',
        string='Product Actual Name',
        readonly=True,
        store=False
    )

    @api.depends('product_id.display_name', 'product_id.default_code', 'product_actual_name')
    def _compute_display_name(self):
        """Override display name to show actual_name when context flag is set"""
        for move in self:
            # Get actual_name from the move's product
            actual_name = move.product_actual_name

            if self._context.get('show_actual_name') and actual_name:
                # Use actual_name when the context flag is set
                name = actual_name
            else:
                # Use the regular product name
                name = move.product_id.name

            # Add default_code prefix if it exists
            default_code = move.product_id.default_code
            if default_code:
                name = f'[{default_code}] {name}'

            move.display_name = name


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # Add actual_name as related field for easy access
    product_actual_name = fields.Char(
        related='product_id.actual_name',
        string='Product Actual Name',
        readonly=True,
        store=False
    )

    @api.depends('product_id.display_name', 'product_id.default_code', 'product_actual_name')
    def _compute_display_name(self):
        """Override display name to show actual_name when context flag is set"""
        for line in self:
            # Get actual_name from the line's product
            actual_name = line.product_actual_name

            if self._context.get('show_actual_name') and actual_name:
                # Use actual_name when the context flag is set
                name = actual_name
            else:
                # Use the regular product name
                name = line.product_id.name

            # Add default_code prefix if it exists
            default_code = line.product_id.default_code
            if default_code:
                name = f'[{default_code}] {name}'

            line.display_name = name