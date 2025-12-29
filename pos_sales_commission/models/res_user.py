# -*- coding: utf-8 -*-
import string

from odoo import _, fields, models


class Users(models.Model):
    _inherit = "res.users"

    def _compute_pos_sale_commission(self):
        commissions = self.env['pos.commission'].search([('user_id', '=', self.id),('employee_id', '=', False)])
        count = 0
        for commission in commissions:
            if(commission.user_id.id == self.id):
                count = count + 1

        self.pos_sale_commission_total = count

    is_commission_applicable = fields.Boolean(string='Commission Applicable')
    pos_sale_commission_total = fields.Integer(compute='_compute_pos_sale_commission', string='Commission')
