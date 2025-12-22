{
    'name': 'Purchase Tolerance',
    'version': '1.0',
    'summary': 'Enforces 15% tolerance on received quantities in purchase orders',
    'description': 'Limits received quantities to 15% more than ordered quantity.',
    'category': 'Purchases',
    'author': 'Generated',
    'depends': ['purchase'],
    'data': [
        'views/purchase_order_line_views.xml',
    ],
    'installable': True,
    'application': False,
}
