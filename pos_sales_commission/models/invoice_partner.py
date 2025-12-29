# -*- coding: utf-8 -*-
import datetime

from odoo import fields, models


class InvoicePartner(models.TransientModel):
    _name = 'invoice.partner'
    _description = "Invoice Partner"

    pos_commission_id = fields.Many2one(
        'pos.commission', string="Commission", readonly=True)
    pos_commission_ids = fields.Many2many(
        'pos.commission', string="Commissions", readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string="Employee", readonly=True)
    partner_id = fields.Many2one('res.partner', string="Partner")
    multiple_records = fields.Boolean(
        'Multiple Records', store='Multiple Records')
    commission_product_id = fields.Many2one('product.product', string="Commission Product")


    def create_invoice(self):
        if(self.multiple_records == False):
            if(self.employee_id and self.partner_id and self.pos_commission_id):
                dict_list = []
                dict_list.append([0, 0, {
                    'name': 'Commission',
                    'quantity': 1,
                    'price_unit': self.pos_commission_id.commission_amount,
                    'product_id': self.commission_product_id,
                    'pos_commission_id': self.pos_commission_id.id,
                }])
                dic_vals = [{
                    'invoice_line_ids': dict_list,
                    'move_type': 'out_invoice',
                    'partner_id': self.partner_id.id,
                    'invoice_date': fields.Datetime.now().date(),
                }]
                invoice = self.env['account.move'].with_context(
                    default_type='out_invoice').create(dic_vals)
                if(not invoice):
                    self.pos_commission_id.state = 'confirm'
                else:
                    self.pos_commission_id.state = 'invoice'
                    self.pos_commission_id.move_id = invoice.id
        else:
            if(self.employee_id):
                if(self.partner_id and self.pos_commission_ids):
                    dict_list = []
                    for pos_commission in self.pos_commission_ids:
                        dict_list.append([0, 0, {
                            'name': 'Commission',
                            'quantity': 1,
                            'price_unit': pos_commission.commission_amount,
                            'product_id': self.commission_product_id,
                            'pos_commission_id': pos_commission.id,
                        }])

                    dic_vals = [{
                        'invoice_line_ids': dict_list,
                        'move_type': 'out_invoice',
                        'partner_id': self.partner_id.id,
                        'invoice_date': fields.Datetime.now().date(),
                    }]
                    invoice = self.env['account.move'].with_context(
                        default_type='out_invoice').create(dic_vals)
                    if(not invoice):
                        for pos_commission in self.pos_commission_ids:
                            pos_commission.state = 'confirm'
                    else:
                        for pos_commission in self.pos_commission_ids:
                            pos_commission.state = 'invoice'
                            pos_commission.move_id = invoice.id
