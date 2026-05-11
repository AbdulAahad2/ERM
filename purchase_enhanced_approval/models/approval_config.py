from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PurchaseApprovalConfig(models.Model):
    _name = 'purchase.approval.config'
    _description = 'Purchase Approval Configuration'
    _order = 'level, sequence'

    name = fields.Char(string='Name', required=True)
    level = fields.Integer(string='Approval Level', required=True,
                          help='The level number in the approval hierarchy (1, 2, 3, etc.)')
    sequence = fields.Integer(string='Sequence', default=10)

    approver_id = fields.Many2one('res.users', string='Approver', required=True,
                                  domain=[('share', '=', False)],
                                  help='User who will approve at this level')
    approver_group_id = fields.Many2one('res.groups', string='Approver Group',
                                       help='Alternative: Any user in this group can approve')

    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    # Optional conditions
    min_amount = fields.Monetary(string='Minimum Amount', currency_field='currency_id')
    max_amount = fields.Monetary(string='Maximum Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    _sql_constraints = [
        ('unique_level_company', 'unique(level, company_id)',
         'Each approval level must be unique per company!')
    ]

    @api.constrains('level')
    def _check_level(self):
        for config in self:
            if config.level < 1:
                raise ValidationError(_('Approval level must be 1 or higher.'))

    @api.constrains('min_amount', 'max_amount')
    def _check_amounts(self):
        for config in self:
            if config.max_amount and config.min_amount and config.max_amount < config.min_amount:
                raise ValidationError(_('Maximum amount must be greater than minimum amount.'))

    @api.constrains('approver_id', 'approver_group_id')
    def _check_approver(self):
        for config in self:
            if not config.approver_id and not config.approver_group_id:
                raise ValidationError(_('Please specify either an Approver or an Approver Group.'))

