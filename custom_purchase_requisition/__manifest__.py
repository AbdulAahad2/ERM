{
    'name': 'Custom Purchase Requisition',
    'version': '1.0',
    'category': 'Purchases',
    'summary': 'Manage purchase requisitions with approval workflow',
    'description': 'A custom module for creating and approving purchase requisitions.',
    'author': 'Your Name',
    'depends': ['purchase', 'base'],
    'data': [
        'security/purchase_requisition_security.xml',
        'security/ir.model.access.csv',
        'views/purchase_requisition_views.xml',
        'views/purchase_requisition_line_views.xml',
        'data/purchase_requisition_data.xml',
    ],
    'installable': True,
    'application': True,
}