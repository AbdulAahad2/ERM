# -*- coding: utf-8 -*-
{
    'name': 'Invoice Journal Sync',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Sync tax and total from journal items to invoice lines with currency support',
    'description': """
        This module synchronizes tax and total amounts from journal items to invoice lines.
        - Takes tax and total from journal items tab
        - Shows them in invoice lines with the currency from journal items
        - If journal item is in USD, tax and total show as USD
        - Other fields remain in company default currency (PKR)
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
        'views/report_invoice.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
