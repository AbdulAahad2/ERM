# -*- coding: utf-8 -*-
{
    "name":  "POS Sales Commission",
    "summary":  """This Module calculates the Commission for the User or Employee based on the Configuration.Commission|Sales Commission|Custom Commission""",
    "category":  "Point of Sale",
    "version":  "1.0.1",
    "sequence":  1,
    "author":  "ERManagers Consulting Services.",
    "license":  "Other proprietary",
    "website":  "https://store.webkul.com/Odoo/POS-Point-of-Sale.html",
    "description":  """Odoo POS Sale Person Commission
Commission
Calculate Sales commisson
Sales Incentive
Total Sales Commission
Commission for Sale
Calculate Commission
Cashier Commission
POS Commission
Sales person Commission""",
    "live_test_url":  "http://odoodemo.webkul.com/?module=wk_pos_sales_commission&custom_url=/pos/auto",
    "depends":  [
        'point_of_sale',
        'pos_hr',
    ],
    "data":  [
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/views.xml',
        'views/show_commission_view.xml',
        'views/res_user_view.xml',
        'views/hr_employee_view.xml',
        'views/product_template_view.xml',
        'views/pos_commission_view.xml',
        'views/wizard_message_view.xml',
        'wizard/commission_report.xml',
        'wizard/invoice_partner.xml',
        'wizard/invoice_data.xml',
        'views/account_move_line_view.xml',
        'report/commission_report.xml',
        'report/commission_report_view.xml',
        'views/res_config_view.xml',
        'views/pos_order_view.xml',
    ],
    "assets": {
        'point_of_sale._assets_pos': [
            "pos_sales_commission/static/src/js/model.js",
            "pos_sales_commission/static/src/js/screen.js",
            "pos_sales_commission/static/src/js/employee_selection_popup.js",
            "pos_sales_commission/static/src/css/pos.css",
            'pos_sales_commission/static/src/xml/**/*',
        ],
    },
    "demo":  ['demo/demo.xml'],
    "images":  ['static/description/Banner.png'],
    "application":  True,
    "installable":  True,
    "auto_install":  False,
    "price":  49,
    "currency":  "PKR",
    "pre_init_hook":  "pre_init_check",
}
