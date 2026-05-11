{
    'name': 'Purchase Vendor Restriction',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Restrict PO to only allow vendors defined on product purchase tab',
    'description': """
        This module validates that the vendor selected on a Purchase Order
        matches one of the vendors defined on the product's Purchase tab.
        If a different vendor is selected, a validation error is raised.
    """,
    'author': 'Custom',
    'depends': ['purchase'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
