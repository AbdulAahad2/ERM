# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosCommission(models.Model):
    _name = 'pos.commission'
    _rec_name = 'order_id'
    _description = "Pos Commission"

    def _get_default_currency_id(self):
        return self.env.company.currency_id.id

    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=_get_default_currency_id, required=True)
    employee_id = fields.Many2one('hr.employee', string="Partner")
    user_id = fields.Many2one('res.users', string="User")
    name = fields.Char('Name', compute='_get_name')
    product_id = fields.Many2one(
        comodel_name='product.product', compute='_get_product_id', string='Commission Product')
    commission_amount = fields.Float(string='Commission', digits=0)
    order_id = fields.Many2one('pos.order', string='Related Order')
    qty = fields.Float(string='Quantity')
    price_unit = fields.Float(string="Unit Price")
    pos_commission_line_ids = fields.One2many(
        'pos.commission.line', 'pos_commission_id', string="POS Commission Line")
    move_id = fields.Many2one('account.move', string="Invoice")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirm'),
        ('invoice', 'Invoiced'),
        ('paid', 'Paid'),
        ('cancel', 'Cancel'),
    ], string='Status', readonly=True, default='draft')

    @api.depends('employee_id', 'user_id')
    def _get_name(self):
        for data in self:
            if(data.employee_id):
                data.name = data.employee_id.name
            else:
                data.name = data.user_id.name

    @api.depends('pos_commission_line_ids')
    def _get_product_id(self):
        for commission in self:
            if(len(commission.pos_commission_line_ids) == 1):
                commission.product_id = commission.pos_commission_line_ids.product_id.id
            else:
                commission.product_id = False

    def action_confirm(self):
        self.state = 'confirm'
        return True

    def action_cancel(self):
        self.state = 'cancel'
        return True

    def create_invoice_button(self):
        commission_product_id = self.order_id.config_id.commission_product_id 
        if(self.state != 'confirm'):
            raise ValidationError(
                "This Record is not in Confirm State or it's already Invoiced")
        else:
            if(self.employee_id):
                invoice_partner_id = self.env['invoice.partner']
                invoice_partner_record_id = invoice_partner_id.create([{'employee_id': self.employee_id.id,
                                                                        'pos_commission_id': self.id,
                                                                        'multiple_records': False, 
                                                                        'commission_product_id':commission_product_id,}])
                return {
                    'name': "Enter Partner to Create Invoice",
                    'view_mode': 'form',
                    'view_id': False,
                    'res_model': 'invoice.partner',
                    'res_id': invoice_partner_record_id.id,
                    'type': 'ir.actions.act_window',
                    'nodestroy': True,
                    'target': 'new',
                }
            else:
                dict_list = []
                dict_list.append([0, 0, {
                    'name': 'Commission',
                    'quantity': 1,
                    'price_unit': self.commission_amount,
                    'product_id': commission_product_id,
                    'pos_commission_id': self.id,
                }])

                dic_vals = [{
                    'invoice_line_ids': dict_list,
                    'move_type': 'out_invoice',
                    'partner_id': self.user_id.partner_id.id,
                    'invoice_date': fields.Datetime.now().date(),
                }]
                invoice = self.env['account.move'].with_context(
                    default_type='out_invoice').create(dic_vals)
                if(not invoice):
                    self.state = 'confirm'
                else:
                    self.state = 'invoice'
                    self.move_id = invoice.id

    @api.model
    def create_invoice(self):
        commission_product_id = self.order_id.config_id.commission_product_id 
        # Check if Single Record
        if(len(self) != 1):
            # Check if different Partners are selected and Check the state of Commisison
            old_partner_id = None
            for record in self:
                if(record.employee_id):
                    new_partner_id = record.employee_id
                    if(old_partner_id):
                        if(old_partner_id != new_partner_id.id):
                            raise ValidationError(
                                'Please select same Partner to create Invoice')

                    partner = record.employee_id.id
                    old_partner_id = partner

                if(not record.employee_id):
                    if(record.user_id):
                        new_partner_id = record.user_id
                        if(old_partner_id):
                            if(old_partner_id != new_partner_id.id):
                                raise ValidationError(
                                    'Please select same Partner to create Invoice')

                        partner = record.user_id.id
                        old_partner_id = partner

                if(record.state != 'confirm'):
                    raise ValidationError(
                        'Some of the record are not in Confirm State or are already Invoiced')

            # Create Invoice
            invoice_commission_ids = []
            employee = None
            user = None
            for record in self:
                if(record.employee_id):
                    employee = self.employee_id.id
                    invoice_commission_ids.append(record.id)
                else:
                    user = self.user_id
                    invoice_commission_ids.append(record)

            if(employee):
                invoice_partner_id = self.env['invoice.partner']
                invoice_partner_record_id = invoice_partner_id.create([{'employee_id': employee,
                                                                        'pos_commission_ids': [(6, 0, invoice_commission_ids)],
                                                                        'multiple_records': True, 
                                                                        'commission_product_id':commission_product_id,}])
                return {
                    'name': "Enter Partner to Create Invoice",
                    'view_mode': 'form',
                    'view_id': False,
                    'res_model': 'invoice.partner',
                    'res_id': invoice_partner_record_id.id,
                    'type': 'ir.actions.act_window',
                    'nodestroy': True,
                    'target': 'new',
                }
            else:
                dict_list = []
                for pos_commission in invoice_commission_ids:
                    dict_list.append([0, 0, {
                        'name': 'Commission',
                        'quantity': 1,
                        'price_unit': pos_commission.commission_amount,
                        'product_id': commission_product_id,
                        'pos_commission_id': pos_commission.id,
                    }])

                dic_vals = [{
                    'invoice_line_ids': dict_list,
                    'move_type': 'out_invoice',
                    'partner_id': user.partner_id.id,
                    'invoice_date': fields.Datetime.now().date(),
                }]

                invoice = self.env['account.move'].with_context(
                    default_type='out_invoice').create(dic_vals)
                if(not invoice):
                    for pos_commission in invoice_commission_ids:
                        pos_commission.state = 'confirm'
                else:
                    for pos_commission in invoice_commission_ids:
                        pos_commission.state = 'invoice'
                        pos_commission.move_id = invoice.id
        else:
            if(self.state != 'confirm'):
                raise ValidationError(
                    "This Record is not in Confirm State or it's already Invoiced")
            else:
                if(self.employee_id):
                    invoice_partner_id = self.env['invoice.partner']
                    invoice_partner_record_id = invoice_partner_id.create([{'employee_id': self.employee_id.id,
                                                                            'pos_commission_id': self.id,
                                                                            'multiple_records': False, 
                                                                            'commission_product_id':commission_product_id,}])
                    return {
                        'name': "Enter Partner to Create Invoice",
                        'view_mode': 'form',
                        'view_id': False,
                        'res_model': 'invoice.partner',
                        'res_id': invoice_partner_record_id.id,
                        'type': 'ir.actions.act_window',
                        'nodestroy': True,
                        'target': 'new',
                    }
                else:
                    dict_list = []
                    dict_list.append([0, 0, {
                        'name': 'Commission',
                        'quantity': 1,
                        'price_unit': self.commission_amount,
                        'product_id': commission_product_id,
                        'pos_commission_id': self.id,
                    }])
                    dic_vals = [{
                        'invoice_line_ids': dict_list,
                        'move_type': 'out_invoice',
                        'partner_id': self.user_id.partner_id.id,
                        'invoice_date': fields.Datetime.now().date(),
                    }]
                    invoice = self.env['account.move'].with_context(
                        default_type='out_invoice').create(dic_vals)
                    if(not invoice):
                        self.state = 'confirm'
                    else:
                        self.state = 'invoice'
                        self.move_id = invoice.id

    def unlink(self):
        if(len(self) != 1):
            for record in self:
                if(record.state == 'invoice' or record.state == 'paid'):
                    raise ValidationError(
                        'Some of the Records are Already Invoiced.')
            return super(PosCommission, self).unlink()
        else:
            if(self.state == 'invoice' or self.state == 'paid'):
                raise ValidationError(
                    'Cannot delete this Record as it Already Invoiced.')
            else:
                return super(PosCommission, self).unlink()

    def button_show_invoice(self):
        if self and self.move_id:
            return {
                'name': 'Invoice',
                'view_type': 'form',
                'view_mode': 'list,form',
                'res_model': 'account.move',
                'view_id': False,
                'type': 'ir.actions.act_window',
                'domain': [('id', '=', [self.move_id.id])],
            }


class PosCommissionLine(models.Model):
    _name = "pos.commission.line"
    _description = "Pos Commission Line"
    
    employee_id = fields.Many2one('hr.employee', string="Partner")
    user_id = fields.Many2one('res.users', string="User")

    product_id = fields.Many2one(
        'product.product', string="Commission Product")
    commission_amount = fields.Float(string='Commission', digits=0)
    order_id = fields.Many2one('pos.order', string='Related Order')
    qty = fields.Float(string='Quantity')
    price_unit = fields.Float(string="Unit Price")
    pos_commission_id = fields.Many2one(
        'pos.commission', string="POS Commission")
    move_id = fields.Many2one('account.move', string='Invoice')
