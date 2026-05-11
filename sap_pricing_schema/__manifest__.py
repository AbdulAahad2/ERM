{
    'name': 'Odoo Pricing Schema',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'SAP S/4HANA-style pricing schema with MRP-based tax calculation',
    'description': """
SAP S/4HANA Pricing Schema for Odoo 18
======================================

This module replicates SAP S/4HANA pricing logic:

* MRP (Maximum Retail Price) as base value for tax calculation
* Taxes calculated on MRP (government reporting)
* Retail/Selling Price derived from:
  * Discounts (% or fixed)
  * Margins (% or fixed)
  * Customer-specific adjustments
* Final selling price always lower/adjusted from MRP
* Tax still references MRP

Features:
---------
* Pricing Schema management with rules
* Customer-specific pricing
* Automatic schema selection in Sales Orders
* Real-time price computation
* Tax calculation based on MRP
* Complete price breakdown visibility
* Centralized GL Account Mapping (set once, use everywhere)
* Automatic GL posting on invoice validation
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'sale',
        'account',
        'product',
    ],
    'data': [
        'security/sap_pricing_security.xml',
        'security/ir.model.access.csv',

        # 1. Load the Views and Actions (This defines the IDs)
        'views/pricing_schema_views.xml',     # action_pricing_schema_templates is here
        'views/pricing_gl_mapping_views.xml', # action_pricing_gl_mapping is here
        'views/product_template_views.xml',
        'views/sale_order_views.xml',

        # 2. Load the Menus (This references the IDs above)
        'views/menu_items.xml',

        'views/res_config_settings_views.xml',

        # 3. Static Data
        'data/demo_data.xml',
    ],
    'demo': [
        'data/demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}