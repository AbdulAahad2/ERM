# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class InvoiceData(models.TransientModel):
    _name = 'invoice.data'
    _description = "Invoice Data"

    start_date = fields.Datetime(required=True)
    end_date = fields.Datetime(required=True)
    report_of = fields.Selection([
            ('employee', 'Employee'),
            ('user', 'User'),
            ], string='Report of', default='employee', required=True)
    employee_id = fields.Many2one('hr.employee', string="Employee")
    user_id = fields.Many2one('res.users', string="User")

    @api.constrains('start_date', 'end_date')
    def check_dates(self): 
        if(self.start_date and self.end_date):
            if(self.end_date < self.end_date):
                raise ValidationError('Start Date Cannot be smaller than End Date')
