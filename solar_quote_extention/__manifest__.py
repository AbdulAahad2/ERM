{
    'name': "Solar Quote Extension",
    'version': '18.0.1.0.0',
    'summary': "Adds detailed solar system specifications and guarantees to sales quotations.",
    'category': 'Sales',
    # --- CRITICAL CHANGE HERE ---
    'depends': ['sale', 'sale_management'],
    # ----------------------------
    'data': [
        'security/ir.model.access.csv',
        'reports/reports.xml',
        'views/sale_order_views.xml',
        'reports/solar_quote_template.xml',
    ],
    'license': 'AGPL-3',
}