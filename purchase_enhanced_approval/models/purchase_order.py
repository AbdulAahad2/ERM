from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Field to paste/select the number from the approval module
    # Domain filters only for 'approved' states
    purchase_approval_ids = fields.Many2many(
        'purchase.approval',
        'purchase_order_approval_rel',
        'purchase_id',
        'approval_id',
        string='Approval References',
        # Ensure the target company matches the current PO's company
        domain="[('state', '=', 'approved'), ('company_id', '=', company_id)]",
        help="Select one or more approved requests."
    )
    is_admin = fields.Boolean(compute='_compute_is_admin')

    # Adding the Department field from HR
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        required=True
    )

    approval_level = fields.Integer(default=0, readonly=True)
    current_approver_id = fields.Many2one('res.users', string='Current Approver', readonly=True)

    def _compute_is_admin(self):
        for record in self:
            record.is_admin = self.env.user.has_group('base.group_system')

    @api.onchange('purchase_approval_ids', 'company_id')
    def _onchange_purchase_approval_ids(self):
        """ Aggregates data from all selected approval records into PO lines """
        if not self.purchase_approval_ids:
            return

            # This line will fail if the model doesn't have department_id
        if not self.department_id and self.purchase_approval_ids[0].department_id:
            self.department_id = self.purchase_approval_ids[0].department_id

        # 2. Aggregate line items (Sum quantities for the same product)
        product_data = {}  # { product_id: {'qty': X, 'desc': Y, 'uom': Z} }

        for approval in self.purchase_approval_ids:
            for line in approval.line_ids:
                p_id = line.product_id.id
                if p_id not in product_data:
                    product_data[p_id] = {
                        'product_id': p_id,
                        'product_qty': line.quantity,
                        'product_uom': line.product_id.uom_po_id.id or line.product_id.uom_id.id,
                        'price_unit': line.product_id.standard_price,
                        'name': line.description or line.product_id.name,
                        'date_planned': fields.Datetime.now(),
                    }
                else:
                    # Increment quantity if product already exists in the dict
                    product_data[p_id]['product_qty'] += line.quantity

        # 3. Reconstruct the order lines
        new_lines = [(5, 0, 0)]  # Clear existing
        for data in product_data.values():
            new_lines.append((0, 0, data))

        self.order_line = new_lines

    def action_send_for_approval(self):  # Renamed from button_confirm
        """ Acts as 'Send for Approval' """
        is_admin = self.env.user.has_group('base.group_system')
        for order in self:
            if not order.department_id:
                raise UserError(_("Please select a Department before sending for approval."))

            # Start the approval process
            first_approver = order.department_id.approver_level_1_id
            if not first_approver:
                raise UserError(_("The selected department has no Level 1 approver assigned."))

            # Set the state to start the chain
            order.write({
                'approval_level': 1,
                'current_approver_id': first_approver.id
            })

            # Trigger notification and activity
            order._create_approval_activity()
            order._send_approval_email()

        return True

    def _create_approval_activity(self):
        if self.current_approver_id:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.current_approver_id.id,
                summary=_("Purchase Approval Required"),
                note=f"Level {self.approval_level} approval requested."
            )

    def action_department_approve(self):
        """ Handles the progression through levels """

        is_admin = self.env.user.has_group('base.group_system')

        if self.current_approver_id != self.env.user and not is_admin:
            raise UserError(_("It is not your turn to approve."))

        self.activity_feedback(['mail.mail_activity_data_todo'])

        next_approver = False
        new_level = self.approval_level

        # Selection Logic
        if self.approval_level == 1:
            next_approver = self.department_id.approver_level_2_id
            new_level = 2
        elif self.approval_level == 2:
            next_approver = self.department_id.approver_level_3_id
            new_level = 3
        elif self.approval_level == 3:
            next_approver = self.department_id.approver_level_4_id
            new_level = 4

        if next_approver:
            self.write({
                'approval_level': new_level,
                'current_approver_id': next_approver.id
            })
            self._create_approval_activity()
        else:
            # FINAL APPROVAL REACHED
            self.write({
                'current_approver_id': False,
                'approval_level': 0
            })
            # 1. Call Odoo's native confirmation (this creates the Picking)
            res = super(PurchaseOrder, self).button_confirm()

            # 2. Make the Delivery "Ready"
            self._prepare_receipts_to_ready()
            return res

    def _prepare_receipts_to_ready(self):
        """
        Sets the associated picking to 'Ready' (Assigned)
        without validating it completely.
        """
        for picking in self.picking_ids.filtered(lambda x: x.state not in ('done', 'cancel')):
            # action_assign() checks stock/constraints and moves state from 'Waiting' to 'Assigned' (Ready)
            picking.action_assign()

    def _send_approval_email(self):
        template = self.env.ref('purchase.email_template_edi_purchase', raise_if_not_found=False)
        if template and self.current_approver_id.email:
            template.send_mail(self.id, force_send=True, email_values={'email_to': self.current_approver_id.email})

    def _auto_validate_receipts(self):
        for picking in self.picking_ids.filtered(lambda x: x.state not in ('done', 'cancel')):
            picking.action_assign()
            for move in picking.move_ids_without_package:
                move.quantity = move.product_uom_qty
            picking.button_validate()