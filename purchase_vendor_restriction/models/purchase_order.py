from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Sirf in categories pe vendor restriction apply hogi
RESTRICTED_CATEGORIES = ['RAW', 'PKG', 'SSP']


def get_category_names(product):
    """Product ki category aur uske saare parents ke naam return karta hai"""
    names = []
    cat = product.categ_id
    while cat:
        names.append(cat.name)
        cat = cat.parent_id
    return names


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.constrains('product_id', 'order_id')
    def _check_vendor_matches_product(self):
        for line in self:
            product = line.product_id
            order = line.order_id
            vendor = order.partner_id

            if not product or not vendor:
                continue

            # Product ki category check karein
            category_names = get_category_names(product)
            is_restricted_category = any(c in RESTRICTED_CATEGORIES for c in category_names)

            # Get all vendors defined on this product's Purchase tab
            product_vendors = self.env['product.supplierinfo'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ])

            if is_restricted_category:
                # RAW / PKG / SSP → vendor ZAROOR match karna chahiye
                if not product_vendors:
                    # Vendor set hi nahi — error do
                    raise ValidationError(_(
                        "Vendor Not Set!\n\n"
                        "Product: %(product)s\n"
                        "Category: %(category)s\n\n"
                        "Is category ki products ke liye product ki Purchase tab mein "
                        "vendor set karna zaroori hai.",
                        product=product.display_name,
                        category=product.categ_id.complete_name,
                    ))

                allowed_vendor_ids = product_vendors.mapped('partner_id').ids
                if vendor.id not in allowed_vendor_ids:
                    allowed_vendor_names = ', '.join(
                        product_vendors.mapped('partner_id.name')
                    )
                    raise ValidationError(_(
                        "Vendor Mismatch!\n\n"
                        "Product: %(product)s\n"
                        "Category: %(category)s\n"
                        "Selected Vendor: %(vendor)s\n\n"
                        "This product can only be purchased from: %(allowed)s\n\n"
                        "Please select the correct vendor or update the "
                        "product's Purchase tab to add this vendor.",
                        product=product.display_name,
                        category=product.categ_id.complete_name,
                        vendor=vendor.name,
                        allowed=allowed_vendor_names,
                    ))

            else:
                # Koi aur category → sirf tab check karo jab vendor set ho
                if not product_vendors:
                    # Vendor set nahi — allow karo, koi restriction nahi
                    continue

                allowed_vendor_ids = product_vendors.mapped('partner_id').ids
                if vendor.id not in allowed_vendor_ids:
                    allowed_vendor_names = ', '.join(
                        product_vendors.mapped('partner_id.name')
                    )
                    raise ValidationError(_(
                        "Vendor Mismatch!\n\n"
                        "Product: %(product)s\n"
                        "Selected Vendor: %(vendor)s\n\n"
                        "This product can only be purchased from: %(allowed)s\n\n"
                        "Please select the correct vendor or update the "
                        "product's Purchase tab to add this vendor.",
                        product=product.display_name,
                        vendor=vendor.name,
                        allowed=allowed_vendor_names,
                    ))


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.constrains('partner_id', 'order_line')
    def _check_all_lines_vendor(self):
        """Vendor change hone par bhi saari lines re-validate hon."""
        for order in self:
            vendor = order.partner_id
            if not vendor:
                continue

            for line in order.order_line:
                product = line.product_id
                if not product:
                    continue

                category_names = get_category_names(product)
                is_restricted_category = any(c in RESTRICTED_CATEGORIES for c in category_names)

                product_vendors = self.env['product.supplierinfo'].search([
                    ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ])

                if is_restricted_category:
                    if not product_vendors:
                        raise ValidationError(_(
                            "Vendor Not Set!\n\n"
                            "Product: %(product)s\n"
                            "Category: %(category)s\n\n"
                            "Is category ki products ke liye product ki Purchase tab mein "
                            "vendor set karna zaroori hai.",
                            product=product.display_name,
                            category=product.categ_id.complete_name,
                        ))

                    allowed_vendor_ids = product_vendors.mapped('partner_id').ids
                    if vendor.id not in allowed_vendor_ids:
                        allowed_vendor_names = ', '.join(
                            product_vendors.mapped('partner_id.name')
                        )
                        raise ValidationError(_(
                            "Vendor Mismatch!\n\n"
                            "Product: %(product)s\n"
                            "Category: %(category)s\n"
                            "Selected Vendor: %(vendor)s\n\n"
                            "This product can only be purchased from: %(allowed)s\n\n"
                            "Please select the correct vendor or update the "
                            "product's Purchase tab to add this vendor.",
                            product=product.display_name,
                            category=product.categ_id.complete_name,
                            vendor=vendor.name,
                            allowed=allowed_vendor_names,
                        ))

                else:
                    if not product_vendors:
                        continue

                    allowed_vendor_ids = product_vendors.mapped('partner_id').ids
                    if vendor.id not in allowed_vendor_ids:
                        allowed_vendor_names = ', '.join(
                            product_vendors.mapped('partner_id.name')
                        )
                        raise ValidationError(_(
                            "Vendor Mismatch!\n\n"
                            "Product: %(product)s\n"
                            "Selected Vendor: %(vendor)s\n\n"
                            "This product can only be purchased from: %(allowed)s\n\n"
                            "Please select the correct vendor or update the "
                            "product's Purchase tab to add this vendor.",
                            product=product.display_name,
                            vendor=vendor.name,
                            allowed=allowed_vendor_names,
                        ))
