{
    'name': 'Purchase Enhanced Approval',
    'version': '1.0.0',
    'category': 'Purchases',
    'summary': 'Enhanced Purchase Requisition and Purchase Order with Multi-Level Approval',
    'description': """
        This module enhances Purchase Requisition and Purchase Order workflows:

        Features:
        - Purchase Requisition with Manager-based approval
        - Plant and Department fields on Purchase Requisition
        - Link between Purchase Requisition and Purchase Order
        - Dynamic multi-level approval based on Product Category
        - Sequential approval workflow with notifications
        - Activity tracking and approval history
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'base',
        'purchase',
        'purchase_requisition',
        'hr',
        'mail',
'purchase_stock'
    ],
    'data': [
        'security/security_rules.xml',
        'security/ir.model.access.csv',
        'data/approval_sequence.xml',
        'views/purchase_requisition_views.xml',
        'views/purchase_order_views.xml',
        'views/product_category_views.xml',
        'views/pr_export_import_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

