# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    """
    Extends purchase.order.line to:
    - Auto-fill product_qty when the selected packaging is flagged as the
      Purchase Packaging (is_purchase_package = True).
    - Expose a computed 'x_packaging_qty' field (number of packs) that the
      user can edit directly; editing it multiplies back to product_qty.
    """

    _inherit = 'purchase.order.line'

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------

    x_packaging_qty = fields.Float(
        string='Packaging Qty',
        digits='Product Unit of Measure',
        default=0.0,
        help=(
            "Number of packages ordered. "
            "Changing this value automatically updates the ordered quantity "
            "(Packaging Qty × Packaging size)."
        ),
    )

    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------

    @api.onchange('product_packaging_id')
    def _onchange_product_packaging_id_purchase(self):
        """
        Auto-set ordered quantity when a purchase-designated packaging is chosen.
        Also recomputes x_packaging_qty to reflect the new packaging.
        """
        packaging = self.product_packaging_id
        if packaging and packaging.is_purchase_package:
            self.product_qty = packaging.qty
            self.x_packaging_qty = 1.0
        elif packaging and packaging.qty:
            self.x_packaging_qty = (
                self.product_qty / packaging.qty
                if packaging.qty else 0.0
            )

    @api.onchange('x_packaging_qty')
    def _onchange_x_packaging_qty(self):
        """
        When the user edits the number-of-packs field, multiply by the
        packaging size and write it back to the ordered quantity.
        """
        packaging = self.product_packaging_id
        if packaging and packaging.qty and self.x_packaging_qty:
            self.product_qty = self.x_packaging_qty * packaging.qty

    @api.onchange('product_qty')
    def _onchange_product_qty_sync_packs(self):
        """
        Keep x_packaging_qty in sync when the user edits product_qty directly.
        """
        packaging = self.product_packaging_id
        if packaging and packaging.qty:
            self.x_packaging_qty = self.product_qty / packaging.qty

    @api.onchange('product_id')
    def _onchange_product_id_set_purchase_packaging(self):
        """
        When a product is changed on a purchase line, pre-select the designated
        purchase packaging (if any) and update the quantity accordingly.
        """
        if not self.product_id:
            self.x_packaging_qty = 0.0
            return

        purchase_pkg = self.env['product.packaging'].search([
            ('product_id', '=', self.product_id.id),
            ('is_purchase_package', '=', True),
        ], limit=1)

        if purchase_pkg:
            self.product_packaging_id = purchase_pkg
            self.product_qty = purchase_pkg.qty
            self.x_packaging_qty = 1.0

    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        res = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        # Pass the custom package count to the stock move
        res['x_packaging_qty'] = self.x_packaging_qty
        return res