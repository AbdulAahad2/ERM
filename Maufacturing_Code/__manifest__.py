{
    'name': 'Manufacturing Auto Code Generator',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Auto-generate codes for semi-finished and finished products',
    'depends': ['mrp'],
    'data': [
        'data/ir_sequence_data.xml',
        'views/product_template_views.xml',
        'views/mrp_production_views.xml',
        'views/stock_lot_views.xml',
    ],
    'web.assets_backend': [
        'Manufacturing_Code/static/src/css/mrp_production.css',
    ],
    'installable': True,
    'application': False,
}