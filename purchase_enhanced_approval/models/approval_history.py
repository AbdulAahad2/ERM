from odoo import models, fields, api


class PurchaseApprovalHistory(models.Model):
    _name = 'purchase.approval.history'
    _description = 'Purchase Order Approval History'
    _order = 'approval_date desc'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order',
                                        required=True, ondelete='cascade')
    level = fields.Integer(string='Approval Level', required=True)
    approver_id = fields.Many2one('res.users', string='Approver', required=True)
    approval_date = fields.Datetime(string='Approval Date', required=True)
    action = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('delegated', 'Delegated')
    ], string='Action', required=True)
    notes = fields.Text(string='Notes')

    # Related fields for display
    po_name = fields.Char(related='purchase_order_id.name', string='PO Reference', store=True)
    partner_id = fields.Many2one(related='purchase_order_id.partner_id', string='Vendor')
    amount_total = fields.Monetary(related='purchase_order_id.amount_total', string='Total Amount')
    currency_id = fields.Many2one(related='purchase_order_id.currency_id')

