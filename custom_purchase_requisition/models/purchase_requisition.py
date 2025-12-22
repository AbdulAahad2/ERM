from odoo import models, fields, api
from odoo.exceptions import UserError
from collections import defaultdict
from datetime import datetime

class PurchaseRequisition(models.Model):
    _name = 'custom.purchase.requisition'
    _description = 'Purchase Requisition'

    name = fields.Char(string='Requisition Reference', required=True, copy=False, readonly=True, default=lambda self: 'New')
    requester_id = fields.Many2one('res.users', string='Requester', default=lambda self: self.env.user)
    department_id = fields.Many2one('hr.department', string='Department')
    date_start = fields.Date(string='Requisition Date', default=fields.Date.today)
    deadline_date = fields.Date(string='Required By')
    hide_unit_price = fields.Boolean(string='Hide Unit Price')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft')
    line_ids = fields.One2many('custom.purchase.requisition.line', 'requisition_id', string='Requisition Lines')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)
    rejection_reason = fields.Text(string='Rejection Reason')
    can_approve = fields.Boolean(string='Can Approve', compute='_compute_can_approve')
    purchase_ids = fields.One2many('purchase.order', 'requisition_id', string='Purchase Orders')
    purchase_count = fields.Integer(string='Purchase Orders', compute='_compute_purchase_count')

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(line.subtotal for line in rec.line_ids)

    @api.depends('department_id')
    def _compute_can_approve(self):
        for rec in self:
            rec.can_approve = self.env.user == rec.department_id.manager_id.user_id

    @api.depends('purchase_ids')
    def _compute_purchase_count(self):
        for rec in self:
            rec.purchase_count = len(rec.purchase_ids)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('custom.purchase.requisition') or 'New'
        return super().create(vals)

    def action_submit(self):
        self.state = 'submitted'
        manager = self.department_id.manager_id.user_id
        if manager and manager.email:
            mail_vals = {
                'email_from': self.env.user.email or 'admin@example.com',
                'email_to': manager.email,
                'subject': f'Requisition {self.name} Approval Request',
                'body_html': f'<p>Please approve requisition {self.name} from {self.requester_id.name}.</p>',
            }
            self.env['mail.mail'].sudo().create(mail_vals).send()

    def action_approve(self):
        self.state = 'approved'

    def action_done(self):
        self.state = 'done'
        requester = self.requester_id
        if requester.email:
            mail_vals = {
                'email_from': self.env.user.email or 'admin@example.com',
                'email_to': requester.email,
                'subject': f'Requisition {self.name} Done',
                'body_html': '<p>Your requisition has been marked as done.</p>',
            }
            self.env['mail.mail'].sudo().create(mail_vals).send()

    def action_cancel(self):
        self.state = 'cancel'

    def action_reject(self):
        if self.env.user != self.department_id.manager_id.user_id:
            raise UserError("Only the department manager can reject the requisition.")
        return {
            'name': 'Reject Requisition',
            'type': 'ir.actions.act_window',
            'res_model': 'custom.purchase.requisition.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_requisition_id': self.id},
        }

    def create_rfq(self):
        if self.state != 'approved':
            return
        vendor_to_lines = defaultdict(list)
        for line in self.line_ids:
            for seller in line.product_id.seller_ids:
                vendor = seller.partner_id
                price_unit = seller.price or line.price_unit
                line_data = {
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                    'product_uom': line.product_uom_id.id,
                    'price_unit': price_unit,
                }
                vendor_to_lines[vendor.id].append(line_data)
        pos = []
        for vendor_id, lines in vendor_to_lines.items():
            order_vals = {
                'partner_id': vendor_id,
                'order_line': [(0, 0, l) for l in lines],
                'requisition_id': self.id,
            }
            if self.deadline_date:
                order_vals['date_order'] = datetime.combine(self.deadline_date, datetime.min.time())
            po = self.env['purchase.order'].create(order_vals)
            pos.append(po.id)
        requester = self.requester_id
        if requester.email:
            mail_vals = {
                'email_from': self.env.user.email or 'admin@example.com',
                'email_to': requester.email,
                'subject': f'Requisition {self.name} RFQs Created',
                'body_html': '<p>RFQs have been created for your requisition.</p>',
            }
            self.env['mail.mail'].sudo().create(mail_vals).send()
        if pos:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'list,form',
                'domain': [('id', 'in', pos)],
            }

    def create_purchase_order(self):
        if self.state != 'approved':
            return
        default_date_order = datetime.combine(self.deadline_date, datetime.min.time()) if self.deadline_date else False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_order_line': [(0, 0, {
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                    'product_uom': line.product_uom_id.id,
                    'price_unit': line.price_unit,
                }) for line in self.line_ids],
                'default_requisition_id': self.id,
                'default_date_order': default_date_order,
            },
        }

    def action_view_purchase_orders(self):
        return {
            'name': 'Purchase Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('requisition_id', '=', self.id)],
        }

class PurchaseRequisitionRejectWizard(models.TransientModel):
    _name = 'custom.purchase.requisition.reject.wizard'
    _description = 'Requisition Reject Wizard'

    requisition_id = fields.Many2one('custom.purchase.requisition', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.requisition_id.write({'state': 'rejected', 'rejection_reason': self.reason})
        requester = self.requisition_id.requester_id
        if requester.email:
            mail_vals = {
                'email_from': self.env.user.email or 'admin@example.com',
                'email_to': requester.email,
                'subject': f'Requisition {self.requisition_id.name} Rejected',
                'body_html': f'<p>Reason: {self.reason}</p>',
            }
            self.env['mail.mail'].sudo().create(mail_vals).send()

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    requisition_id = fields.Many2one('custom.purchase.requisition', string='Purchase Requisition')

    def button_confirm(self):
        res = super().button_confirm()
        if self.requisition_id and self.requisition_id.state == 'approved':
            self.requisition_id.state = 'done'
            requester = self.requisition_id.requester_id
            if requester.email:
                mail_vals = {
                    'email_from': self.env.user.email or 'admin@example.com',
                    'email_to': requester.email,
                    'subject': f'Requisition {self.requisition_id.name} Done',
                    'body_html': '<p>Your requisition has been marked as done. Purchase orders created and confirmed.</p>',
                }
                self.env['mail.mail'].sudo().create(mail_vals).send()
        return res

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super().button_validate()
        if self.state == 'done' and self.picking_type_id.code == 'incoming' and self.purchase_id.requisition_id:
            requester = self.purchase_id.requisition_id.requester_id
            if requester.email:
                mail_vals = {
                    'email_from': self.env.user.email or 'admin@example.com',
                    'email_to': requester.email,
                    'subject': f'Requisition {self.purchase_id.requisition_id.name} Delivered',
                    'body_html': '<p>Your requested items have been delivered.</p>',
                }
                self.env['mail.mail'].sudo().create(mail_vals).send()
        return res