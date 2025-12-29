# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployeePrivate(models.Model):
    _inherit = "hr.employee"

    def _compute_pos_sale_commission(self):
        """Compute total commissions for this employee"""
        for employee in self:
            commissions = self.env['pos.commission'].search([
                ('employee_id', '=', employee.id)
            ])
            employee.pos_sale_commission_total = len(commissions)

    is_commission_applicable = fields.Boolean(
        string='Commission Applicable',
        help='Enable this to make the employee eligible for POS commissions'
    )
    is_veterinarian = fields.Boolean(
        string='Is Veterinarian',
        help='Mark this employee as a veterinarian'
    )
    pos_sale_commission_total = fields.Integer(
        compute='_compute_pos_sale_commission',
        string='Commission Count',
        help='Total number of commissions for this employee'
    )

    def action_view_commissions(self):
        """Open commissions for this employee"""
        self.ensure_one()
        return {
            'name': 'Commissions',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.commission',
            'view_mode': 'tree,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id}
        }
