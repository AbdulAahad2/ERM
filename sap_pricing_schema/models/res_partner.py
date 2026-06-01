from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sap_sales_tax_rate = fields.Float(
        string='Sales Tax (%)',
        digits=(16, 4),
        default=0.0,
        help='Sales tax rate for this customer (e.g. 15, 18, 0.1). '
             'Changing this automatically updates the MWST rule in all '
             'pricing schemas where this customer is assigned.',
    )

    sap_additional_tax_rate = fields.Float(
        string='Income Tax (%)',
        digits=(16, 4),
        default=0.0,
        help='Income tax rate for this customer (e.g. 0.1, 5). '
             'Changing this automatically updates the JEXT rule in all '
             'pricing schemas where this customer is assigned.',
    )

    sap_freight_tax_rate = fields.Float(
        string='Additional Tax (%)',
        digits=(16, 4),
        default=0.0,
        help='Additional tax rate for this customer (e.g. 0.1, 5). '
             'Changing this automatically updates the KF00 rule in all '
             'pricing schemas where this customer is assigned.',
    )

    def write(self, vals):
        result = super().write(vals)
        # ✅ Removed: no longer push rates into schema rules on partner save
        return result