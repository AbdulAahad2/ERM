from odoo import models, fields, api, _

class AccountMove(models.Model):
    _inherit = 'account.move'

    tax_is_submitted = fields.Boolean(
        string="Tax Submission Check",
        default=False,
        copy=False,
        tracking=True
    )

    tax_submission_status = fields.Selection([
        ('not_submitted', 'Not Submitted'),
        ('submitted', 'Submitted')
    ], string="Submission Status", default='not_submitted', store=True, tracking=True)

    tax_submission_date = fields.Date(string="Submission Date", tracking=True)

    tax_submission_period = fields.Char(
        string="Submission Period",
        compute="_compute_tax_period",
        store=True
    )

    @api.depends('tax_submission_date')
    def _compute_tax_period(self):
        for move in self:
            if move.tax_submission_date:
                move.tax_submission_period = move.tax_submission_date.strftime('%B %Y')
            else:
                move.tax_submission_period = False

    def write(self, vals):
        if 'tax_is_submitted' in vals:
            if vals['tax_is_submitted']:
                # FIX: Only set to context_today if the wizard didn't provide a date
                if 'tax_submission_date' not in vals:
                    vals.update({
                        'tax_submission_status': 'submitted',
                        'tax_submission_date': fields.Date.context_today(self)
                    })
                else:
                    vals['tax_submission_status'] = 'submitted'
            else:
                vals.update({
                    'tax_submission_status': 'not_submitted',
                    'tax_submission_date': False
                })
        return super(AccountMove, self).write(vals)

    def action_submit_tax(self):
        """ This now opens the wizard pop-up instead of updating directly """
        return {
            'name': _('Select Tax Submission Date'),
            'type': 'ir.actions.act_window',
            'res_model': 'tax.submission.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_ids': self.ids},
        }

    @api.onchange('tax_is_submitted')
    def _onchange_tax_is_submitted(self):
        if self.tax_is_submitted:
            self.tax_submission_status = 'submitted'
            self.tax_submission_date = fields.Date.context_today(self)
        else:
            self.tax_submission_status = 'not_submitted'
            self.tax_submission_date = False

# --- NEW WIZARD CLASS ---
class TaxSubmissionWizard(models.TransientModel):
    _name = 'tax.submission.wizard'
    _description = 'Tax Submission Wizard'

    submission_date = fields.Date(
        string="Submission Date",
        default=fields.Date.context_today,
        required=True
    )

    def action_confirm(self):
        # Gets the invoices you selected in the list view
        active_ids = self.env.context.get('active_ids')
        records = self.env['account.move'].browse(active_ids)
        # Writes the date from the wizard to all selected records
        records.write({
            'tax_is_submitted': True,
            'tax_submission_date': self.submission_date
        })