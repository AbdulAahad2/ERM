from odoo import models, fields, api
from odoo.exceptions import UserError

class RequisitionReportWizard(models.TransientModel):
    _name = 'requisition.report.wizard'
    _description = 'Requisition Report Wizard'

    # Suggestion: Default the employee if opened from a record
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    date_from = fields.Date(string='Date From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.context_today)

    def action_print_report(self):
        domain = [
            ('employee_id', '=', self.employee_id.id),
            ('create_date', '>=', self.date_from),
            ('create_date', '<=', self.date_to),
        ]
        requisitions = self.env['employee.requisition'].search(domain)

        if not requisitions:
            raise UserError("No records found for this employee in the selected date range.")

        # Trigger the report and pass dates via context
        return self.env.ref('employee_requisition_advanced.action_report_employee_requisition').with_context(
            date_from=self.date_from,
            date_to=self.date_to
        ).report_action(requisitions)