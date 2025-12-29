# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    pos_commission_id = fields.Many2one(
        'pos.commission', string="POS Commission")

    @api.model_create_multi
    def create(self, vals_list):
        results = super(AccountMoveLine, self).create(vals_list)
        for result in results:
            result.tax_ids = False
        return results


class AccountMove(models.Model):
    _inherit = "account.move"

    def write(self, vals):
        result = super().write(vals)
        if result and self:
            for rec in self:
                move_id = self.search([('name', '=', rec.ref)], limit=1)
                if move_id and move_id.payment_state == 'paid':
                    for line in move_id.invoice_line_ids:
                        line.pos_commission_id.write({"state": "paid"})
        return result

