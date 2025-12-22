from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    branch_code = fields.Char(
        string="Branch Code",
        size=10,
        help="Unique code to identify this branch (e.g., HT, BK, MD)",
        copy=False,
        tracking=True
    )

    _sql_constraints = [
        ('branch_code_unique', 'unique(branch_code)', 'Branch Code must be unique!')
    ]

    @api.constrains('branch_code')
    def _check_branch_code(self):
        for record in self:
            if record.branch_code:
                # Check if code contains only alphanumeric characters (no spaces or special chars)
                if not record.branch_code.replace('-', '').replace('_', '').isalnum():
                    raise ValidationError(_("Branch Code can only contain letters, numbers, hyphens, and underscores."))
                
                # Optional: Enforce uppercase
                if record.branch_code != record.branch_code.upper():
                    record.branch_code = record.branch_code.upper()
