{
    'name': 'Payment Due Notifications',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Send notifications before payment due date with configurable timing',
    'description': """
        This module sends notifications before a payment is due.
        Features:
        - Configurable notification timing (days, hours, or minutes)
        - Automatic notification based on settings
        - Inbox/bell notifications for salespeople
        - Email notifications
        - In-app activity notifications
        - Scheduled action for checks
        - Easy testing with flexible time settings
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['account', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/mail_message_subtype_data.xml',
        'views/payment_notification_config_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}