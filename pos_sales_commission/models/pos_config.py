# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    @api.depends()
    def _compute_auto_validate_pos_sale_commission(self):
        val = self.env['ir.default'].sudo()._get('res.config.settings', 'create_invoice_at_order_validation')
        self.is_auto_validate_pos_sale_commission = val

    is_use_pos_commission = fields.Boolean(string='Enable POS Sale Commision', default=True)
    show_apply_commission = fields.Boolean(string='Show Apply Commission Button', default=True)
    sale_commission_id = fields.Many2one('pos.sale.commission', string="Default Commission" )
    is_auto_validate_pos_sale_commission = fields.Boolean(string="Auto Validate POS Sale Commission", compute='_compute_auto_validate_pos_sale_commission')
    commission_product_id = fields.Many2one('product.product', string="Commission Product")
   
