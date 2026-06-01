# -*- coding: utf-8 -*-
{
    'name': 'Product Packaging Extended',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Products',
    'summary': 'Extend Product Packaging with Sales & Purchase strict selection rules',
    'description': """
        This module extends the product.packaging model to add:
        - is_sales_package: Marks a packaging as the default for Sales Orders
        - is_purchase_package: Marks a packaging as the default for Purchase Orders

        Enforces that only ONE packaging per product can be flagged for sales
        and only ONE for purchase (using @api.constrains).

        Auto-fills order line quantity when the flagged packaging is selected.
    """,
    'author': 'Custom Development',
    'depends': [
        'product',
        'sale_management',
        'sale_stock',
        'account',
        'purchase',
    ],
    'data': [
        'views/product_packaging_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
