# -*- coding: utf-8 -*-
{
    'name': 'Product Actual Name',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Add actual name field to products with custom search behavior',
    'description': """
        This module adds an 'actual_name' field to products.
        - Searchable by actual name in RFQ, Purchase Orders, Sales Orders, and Invoices
        - GRN shows product reference/default_code (e.g., 0001)
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['product', 'purchase', 'stock', 'sale', 'account'],
    'data': [
        'views/product_template_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
