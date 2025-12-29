# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    auto_confirm_at_order_validation = fields.Boolean(
        string="Auto Confirm at Order Validation")
    create_commission = fields.Selection([
        ('single', 'Commission by Order'),
        ('multiple', 'Commission by Product')],
        default='single', string='Commission')

    # pos_config_fields
    is_use_pos_commission = fields.Boolean(
        string='Enable POS Sale Commision', default=True, related="pos_config_id.is_use_pos_commission", readonly=False)
    show_apply_commission = fields.Boolean(string='Show Apply Commission Button',
                                           default=True, related="pos_config_id.show_apply_commission", readonly=False)
    sale_commission_id = fields.Many2one(
        'pos.sale.commission', string="Default Commission", related="pos_config_id.sale_commission_id", readonly=False)
    commission_product_id = fields.Many2one(
        'product.product', string="Commission Product", related="pos_config_id.commission_product_id", readonly=False)
    is_auto_validate_pos_sale_commission = fields.Boolean(
        string="Auto Validate POS Sale Commission", compute='_compute_auto_validate_pos_sale_commission', related="pos_config_id.is_auto_validate_pos_sale_commission", readonly=False)

    @api.model
    def res_config_settings_enable(self):
        enable_env = self.env['res.config.settings'].create({'sale_commission_id': self.env.ref('pos_sales_commission.pos_sale_commission_1').id,
                                                            'commission_product_id': self.env.ref('pos_sales_commission.commission_product_1').id})
        enable_env.execute()

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        IrDefault = self.env['ir.default'].sudo()
        IrDefault.set('res.config.settings', 'is_use_pos_commission',
                      self.is_use_pos_commission)
        IrDefault.set('res.config.settings',
                      'show_apply_commission', self.show_apply_commission)        
        IrDefault.set('res.config.settings', 'sale_commission_id',
                      self.sale_commission_id.id)
        IrDefault.set('res.config.settings',
                      'commission_product_id', self.commission_product_id.id)
        IrDefault.set('res.config.settings', 'auto_confirm_at_order_validation',
                      self.auto_confirm_at_order_validation)
        IrDefault.set('res.config.settings', 'create_commission',
                      self.create_commission)
        return True

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        IrDefault = self.env['ir.default'].sudo()
        res.update(
            {'is_use_pos_commission': IrDefault._get('res.config.settings', 'is_use_pos_commission') or False,
             'show_apply_commission': IrDefault._get('res.config.settings', 'show_apply_commission') or False,
             'commission_product_id': IrDefault._get('res.config.settings', 'commission_product_id') or False,
             'sale_commission_id': IrDefault._get('res.config.settings', 'sale_commission_id') or False,
             'auto_confirm_at_order_validation': IrDefault._get('res.config.settings', 'auto_confirm_at_order_validation') or False,
             'create_commission': IrDefault._get('res.config.settings', 'create_commission') or 'single',
             }
        )
        return res
