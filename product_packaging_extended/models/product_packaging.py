# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductPackaging(models.Model):
    """
    Extends product.packaging to support strict single-selection rules
    for Sales and Purchase packaging designation.

    Rules enforced:
    - Only ONE packaging per product may have is_sales_package = True
    - Only ONE packaging per product may have is_purchase_package = True
    """

    _inherit = 'product.packaging'

    is_sales_package = fields.Boolean(
        string='Sales Packaging',
        default=False,
        help=(
            "Mark this packaging as the default for Sales Orders. "
            "When a sales order line selects this packaging, the ordered "
            "quantity will be automatically set to this packaging quantity. "
            "Only ONE packaging per product may have this enabled."
        ),
    )

    is_purchase_package = fields.Boolean(
        string='Purchase Packaging',
        default=False,
        help=(
            "Mark this packaging as the default for Purchase Orders. "
            "When a purchase order line selects this packaging, the ordered "
            "quantity will be automatically set to this packaging quantity. "
            "Only ONE packaging per product may have this enabled."
        ),
    )

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------

    @api.constrains('is_sales_package', 'product_id')
    def _check_unique_sales_package(self):
        """
        Enforce that at most one packaging per product has is_sales_package=True.

        Iterates over all changed records; for each that has is_sales_package
        enabled it searches for any *other* packaging on the same product that
        is also enabled, and raises a ValidationError if found.

        Multi-record safe: the search excludes the current record set so that
        bulk-write operations (e.g. importing a batch) are evaluated correctly.
        """
        for packaging in self.filtered('is_sales_package'):
            duplicate = self.search([
                ('product_id', '=', packaging.product_id.id),
                ('is_sales_package', '=', True),
                ('id', '!=', packaging.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    "Only one Sales Packaging is allowed per product.\n"
                    "Product: '%s' already has '%s' set as the Sales Packaging."
                    % (packaging.product_id.display_name, duplicate.name)
                )

    @api.constrains('is_purchase_package', 'product_id')
    def _check_unique_purchase_package(self):
        """
        Enforce that at most one packaging per product has is_purchase_package=True.

        Same multi-record safety pattern as _check_unique_sales_package.
        """
        for packaging in self.filtered('is_purchase_package'):
            duplicate = self.search([
                ('product_id', '=', packaging.product_id.id),
                ('is_purchase_package', '=', True),
                ('id', '!=', packaging.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    "Only one Purchase Packaging is allowed per product.\n"
                    "Product: '%s' already has '%s' set as the Purchase Packaging."
                    % (packaging.product_id.display_name, duplicate.name)
                )

    # -------------------------------------------------------------------------
    # Onchange – UX: auto-untick siblings when this record is ticked
    # -------------------------------------------------------------------------

    @api.onchange('is_sales_package')
    def _onchange_is_sales_package(self):
        """
        When the user enables is_sales_package on a packaging that lives inside
        the product form's packaging One2many, automatically untick all other
        rows for the same product so the user gets immediate visual feedback
        without waiting for the save-time constraint.

        NOTE: onchange only fires in the UI; the @api.constrains above
        remains the authoritative server-side guard.
        """
        if not self.is_sales_package:
            return

        # _origin gives us the database id for an existing record;
        # for a new (unsaved) record _origin.id is False/NewId.
        current_id = self._origin.id

        # Search existing DB records for this product that are already flagged
        if self.product_id:
            siblings = self.env['product.packaging'].search([
                ('product_id', '=', self.product_id.id),
                ('is_sales_package', '=', True),
                ('id', '!=', current_id),
            ])
            if siblings:
                siblings.write({'is_sales_package': False})
                return {
                    'warning': {
                        'title': 'Sales Packaging Updated',
                        'message': (
                            "The Sales Packaging flag has been moved to '%s'. "
                            "All other packagings for this product have been "
                            "automatically unchecked."
                        ) % self.name,
                    }
                }

    @api.onchange('is_purchase_package')
    def _onchange_is_purchase_package(self):
        """
        When the user enables is_purchase_package on a packaging, automatically
        untick all sibling packagings for the same product.

        Same rationale as _onchange_is_sales_package.
        """
        if not self.is_purchase_package:
            return

        current_id = self._origin.id

        if self.product_id:
            siblings = self.env['product.packaging'].search([
                ('product_id', '=', self.product_id.id),
                ('is_purchase_package', '=', True),
                ('id', '!=', current_id),
            ])
            if siblings:
                siblings.write({'is_purchase_package': False})
                return {
                    'warning': {
                        'title': 'Purchase Packaging Updated',
                        'message': (
                            "The Purchase Packaging flag has been moved to '%s'. "
                            "All other packagings for this product have been "
                            "automatically unchecked."
                        ) % self.name,
                    }
                }
