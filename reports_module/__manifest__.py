{
    'name': 'Picking List',
    'version': '1.0',
    'category': 'Inventory',
    'depends': ['stock', 'sale'],
    'data': [

        'views/report_template.xml',  # <--- Template MUST be first
        'views/report_action.xml',
        'views/picking_view.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}