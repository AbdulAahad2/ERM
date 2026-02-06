{
    'name': 'Account Tax Submission Tracking',
    'version': '1.0',
    'category': 'Accounting',
    'summary': 'Track tax submission status on invoices',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_view.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}