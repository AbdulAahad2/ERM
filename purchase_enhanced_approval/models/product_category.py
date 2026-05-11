from odoo import models, fields

class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # Defining the 4 approval categories/levels
    approver_level_1_id = fields.Many2one('res.users', string='Level 1 Approver (HOD)')
    approver_level_2_id = fields.Many2one('res.users', string='Level 2 Approver (Finance)')
    approver_level_3_id = fields.Many2one('res.users', string='Level 3 Approver (Director)')
    approver_level_4_id = fields.Many2one('res.users', string='Level 4 Approver (CEO)')