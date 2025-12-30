{
    'name': 'Auto Generate Lots',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Auto-generate lot numbers based on vendor codes',
    'depends': ['stock', 'base','mrp'],
    'data': [
        'views/res_partner_views.xml',
        'views/mrp_production_views.xml',
        'views/stock_picking_views.xml',
        'views/product_views.xml',

    ],
    'installable': True,
    'application': False,
}