from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PurchaseApproval(models.Model):
    _name = 'purchase.approval'
    _description = 'Purchase Approval Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    date = fields.Date(string='Date', default=fields.Date.context_today)
    rejection_reason = fields.Text(string="Rejection Reason", readonly=True, copy=False)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse (Plant)')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    # New Field: Department
    department_id = fields.Many2one('hr.department', string='Department', required=True)

    requester_id = fields.Many2one('res.users', string='Requester', default=lambda self: self.env.user)
    approver_id = fields.Many2one('res.users', string='Approver', tracking=True)
    line_ids = fields.One2many('purchase.approval.line', 'approval_id', string='Order Lines')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_approval', 'Waiting Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    is_current_user_approver = fields.Boolean(compute='_compute_is_current_user_approver')

    @api.depends('approver_id')
    def _compute_is_current_user_approver(self):
        for rec in self:
            rec.is_current_user_approver = (rec.approver_id == self.env.user)

    def action_submit_for_approval(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('You cannot submit an empty request.'))

            # Logic changed: Look for the manager assigned to the selected Department
            if not rec.department_id.manager_id:
                raise UserError(_('The selected department does not have a Manager assigned.'))

            manager_user = rec.department_id.manager_id.user_id
            if not manager_user:
                raise UserError(_('The Manager of this department does not have a User account linked.'))

            rec.approver_id = manager_user.id
            rec.state = 'waiting_approval'
            rec.activity_schedule('mail.mail_activity_data_todo', user_id=rec.approver_id.id,
                                  summary=_('PR Approval Required: %s') % rec.name)

    def action_reject_wizard(self):
        """Opens the wizard to provide a rejection reason."""
        return {
            'name': _('Reason for Rejection'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_approval_id': self.id}
        }

    def action_approve(self):
        for rec in self:
            if rec.approver_id != self.env.user:
                raise UserError(_('Only the assigned manager can approve.'))

            # Mark the 'To Do' activity as Done
            rec.activity_feedback(['mail.mail_activity_data_todo'])

            rec.write({'state': 'approved'})
            rec.message_post(body=_("PR Approved by Manager."))

    def action_reject(self):
        for rec in self:
            if rec.approver_id != self.env.user:
                raise UserError(_('Only the assigned manager can reject.'))
            rec.write({'state': 'draft'})
            rec.message_post(body=_("PR Rejected and reset to Draft by Manager."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                # 'purchase.approval' matches the 'code' in the XML record above
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.approval') or _('New')
        return super(PurchaseApproval, self).create(vals_list)


class PurchaseApprovalLine(models.Model):
    _name = 'purchase.approval.line'
    _description = 'Purchase Approval Line'

    approval_id = fields.Many2one('purchase.approval', string='Approval Reference', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    description = fields.Char(string='Description', related='product_id.display_name', readonly=False)
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', related='product_id.uom_id', readonly=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.name


class PurchaseApprovalRejectWizard(models.TransientModel):
    _name = 'purchase.approval.reject.wizard'
    _description = 'Reject Purchase Approval Wizard'

    approval_id = fields.Many2one('purchase.approval', string="Request")
    reason = fields.Text(string="Reason", required=True)

    def action_reject_confirm(self):
        # 1. Update the record state and reason
        self.approval_id.write({
            'state': 'rejected',
            'rejection_reason': self.reason
        })

        # 2. Mark the approver's activity as done
        self.approval_id.activity_feedback(
            ['mail.mail_activity_data_todo'],
            feedback=_("Rejected: %s") % self.reason
        )

        # 3. Schedule a new activity for the Requester
        self.approval_id.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=self.approval_id.requester_id.id,
            summary=_('Purchase Request Rejected'),
            note=_('Your request was rejected for the following reason: %s') % self.reason
        )

        # 4. Post message to chatter
        self.approval_id.message_post(
            body=_("<b>Request Rejected.</b><br/>Reason: %s") % self.reason,
            subtype_xmlid="mail.mt_comment"
        )