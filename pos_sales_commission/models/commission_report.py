# -*- coding: utf-8 -*-
import datetime
from datetime import datetime

import pytz
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionReport(models.TransientModel):
    _name = 'commission.report'
    _description = 'Report of all the Commissions'

    def _wk_get_utc_time_(self, session_date):
        if session_date:
            try:
                session_date = datetime.strptime(
                    session_date, "%Y-%m-%d %H:%M:%S")
                tz_name = self._context.get('tz') or self.env.user.tz
                tz = tz_name and pytz.timezone(tz_name) or pytz.UTC
                return fields.Datetime.to_string((pytz.UTC.localize(session_date.replace(tzinfo=None), is_dst=False).astimezone(tz).replace(tzinfo=None)))

            except ValueError:
                return session_date

    def _get_default_currency_id(self):
        return self.env.company.currency_id.id

    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=_get_default_currency_id, required=True)
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
            if(self.start_date > self.end_date):
                raise ValidationError(
                    'Start Date should be smaller than End Date')

    def generate_commission_report(self):
        end_date = self._wk_get_utc_time_(str(self.end_date))
        start_date = self._wk_get_utc_time_(str(self.start_date))
        if(start_date > end_date):
            raise ValidationError('End Date Cannot be smaller the Start Date')
        if(self.report_of == 'employee'):
            pos_commission_ids = self.env['pos.commission'].search(
                [('create_date', '<=', end_date), ('create_date', '>=', start_date), ('employee_id', '=', self.employee_id.id)])
            if(not len(pos_commission_ids)):
                raise ValidationError(
                    'Cannot Find Records from particular dates')
            commission_lines = []
            name = None
            total = 0
            for pos_commission_id in pos_commission_ids:
                name = pos_commission_id.employee_id.name
                data = {}
                data['name'] = pos_commission_id.employee_id.name
                data['order'] = pos_commission_id.order_id.name
                data['date'] = pos_commission_id.create_date.date()
                if(pos_commission_id.state == 'draft'):
                    data['state'] = 'Draft'
                elif(pos_commission_id.state == 'confirm'):
                    data['state'] = 'Confirm'
                elif(pos_commission_id.state == 'cancel'):
                    data['state'] = 'Cancel'
                elif(pos_commission_id.state == 'invoice'):
                    data['state'] = 'Invoice'
                elif(pos_commission_id.state == 'paid'):
                    data['state'] = 'Paid'
                data['commission'] = "{0:.2f}".format(
                    pos_commission_id.commission_amount)
                total = total + pos_commission_id.commission_amount
                commission_lines.append(data)

            data = {'start_date': start_date, 'end_date': end_date, 'title': name,
                    'commission_lines': commission_lines, 'total': "{0:.2f}".format(total), 'currency_id': self.currency_id}
        else:
            pos_commission_ids = self.env['pos.commission'].search([('create_date', '<=', end_date), (
                'create_date', '>=', start_date), ('user_id', '=', self.user_id.id), ('employee_id', '=', False)])
            if(not len(pos_commission_ids)):
                raise ValidationError(
                    'Cannot Find Records from particular dates')
            commission_lines = []
            name = None
            total = 0
            for pos_commission_id in pos_commission_ids:
                name = pos_commission_id.user_id.name
                data = {}
                data['name'] = pos_commission_id.user_id.name
                data['order'] = pos_commission_id.order_id.name
                data['date'] = pos_commission_id.create_date.date()
                if(pos_commission_id.state == 'draft'):
                    data['state'] = 'Draft'
                elif(pos_commission_id.state == 'confirm'):
                    data['state'] = 'Confirm'
                elif(pos_commission_id.state == 'cancel'):
                    data['state'] = 'Cancel'
                elif(pos_commission_id.state == 'invoice'):
                    data['state'] = 'Invoice'
                elif(pos_commission_id.state == 'paid'):
                    data['state'] = 'Paid'
                data['commission'] = "{0:.2f}".format(
                    pos_commission_id.commission_amount)
                total = total + pos_commission_id.commission_amount
                commission_lines.append(data)

            data = {'start_date': start_date, 'end_date': end_date, 'title': name,
                    'commission_lines': commission_lines, 'total': "{0:.2f}".format(total), 'currency_id': self.currency_id}

        return self.env.ref('pos_sales_commission.action_pos_sales_commission_summary').report_action([], data)
