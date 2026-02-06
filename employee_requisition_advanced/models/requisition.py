from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EmployeeRequisition(models.Model):
    _name = 'employee.requisition'
    _description = 'Employee Purchase Requisition'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # --- Fields ---
    can_approve = fields.Boolean(compute='_compute_can_approve')
    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True,
                                  default=lambda self: self.env.user.employee_id)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', store=True)
    line_ids = fields.One2many('employee.requisition.line', 'requisition_id', string='Requisition Lines')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    total_amount = fields.Monetary(string='Total Amount', compute='_compute_total', store=True)
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain="[('supplier_rank', '>', 0)]")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('manager_approval', 'Manager Approval'),
        ('ceo_approval', 'CEO Approval'),
        ('approved', 'Approved'),
        ('done', 'PO Created'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', tracking=True)

    cancel_reason = fields.Text(string="Cancel Reason")
    max_unit_price = fields.Monetary(string="Max Unit Price", compute="_compute_max_unit_price", store=True)
    purchase_order_ids = fields.Many2many('purchase.order', string='Purchase Orders', readonly=True)

    # --- Compute Methods ---
    @api.depends('line_ids.unit_price')
    def _compute_max_unit_price(self):
        for req in self:
            prices = req.line_ids.mapped('unit_price')
            req.max_unit_price = max(prices) if prices else 0.0

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for req in self:
            req.total_amount = sum(line.subtotal for line in req.line_ids)

    def _compute_can_approve(self):
        for req in self:
            can = False
            # CEO can approve at any stage
            if req._is_ceo():
                can = True
            elif req.state == 'manager_approval':
                can = req._is_department_manager()
            elif req.state == 'ceo_approval':
                can = req._is_ceo()
            req.can_approve = can

    # --- Approval Logic ---
    def action_submit(self):
        for req in self:
            # Route based on amount thresholds
            amount = req.total_amount

            if amount > 10000000:
                # Needs CEO approval - go through all levels
                req.state = 'manager_approval'
            else:
                # Only needs manager approval
                req.state = 'manager_approval'

            # Create activity for the manager
            manager = req._get_manager()
            if manager:
                req._create_activity(manager, 'Approval required: Employee Requisition')

    def action_approve(self):
        for req in self:
            amount = req.total_amount
            req._clear_activities()

            # CEO can approve directly at any stage
            if req._is_ceo():
                req.state = 'approved'
                continue

            if req.state == 'manager_approval':
                # Check if current user is authorized to approve at manager level
                is_own_manager = req._is_department_manager()
                is_self_requisition = (req.env.user.employee_id == req.employee_id)

                # Allow self-approval for managers on their own requisitions below threshold
                if is_self_requisition and is_own_manager and amount <= 10000000:
                    req.state = 'approved'
                elif not is_own_manager:
                    raise UserError(_("Only the department manager or CEO can approve."))
                else:
                    # Manager approved, check if needs higher approval
                    if amount > 10000000:
                        req.state = 'ceo_approval'
                        # Create activity for CEO
                        ceo = req._get_employee_by_job('chief executive officer')
                        if ceo:
                            req._create_activity(ceo, 'CEO Approval required: Employee Requisition')
                    else:
                        req.state = 'approved'

            elif req.state == 'ceo_approval':
                if not req._is_ceo():
                    raise UserError(_("Only the CEO can approve."))
                req.state = 'approved'

    def action_cancel(self):
        self.ensure_one()
        if not self.cancel_reason:
            raise UserError(_("Please provide a reason for cancellation."))
        self.state = 'cancel'

    def action_create_po_manual(self):
        """
        Assigns vendors if missing and generates POs.
        If only one PO is created, it opens that PO form directly.
        """
        self.ensure_one()

        # Assign vendors automatically if not selected
        for line in self.line_ids:
            if not line.vendor_id:
                sellers = line.product_id.seller_ids.sorted(key=lambda s: s.price)
                if sellers:
                    line.vendor_id = sellers[0].partner_id

        if not all(line.vendor_id for line in self.line_ids):
            raise UserError(_("Please ensure all lines have a vendor assigned."))

        return self._generate_purchase_orders()

    def action_create_rfq_per_vendor(self):
        """Open vendor selection wizard"""
        self.ensure_one()

        if not self.line_ids:
            raise UserError(_("No lines to create RFQs."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Vendors for RFQ'),
            'res_model': 'vendor.selection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_requisition_id': self.id,
            },
        }

    def _generate_purchase_orders(self):
        self.ensure_one()
        PurchaseOrder = self.env['purchase.order']
        # Get unique vendors assigned to the lines
        vendors = self.line_ids.mapped('vendor_id')

        po_records = self.env['purchase.order']
        for vendor in vendors:
            lines_for_vendor = self.line_ids.filtered(lambda l: l.vendor_id == vendor)
            po_lines = []

            for line in lines_for_vendor:
                # --- PRICE LOGIC START ---
                # Search for the specific price for THIS vendor on the product
                seller = line.product_id.seller_ids.filtered(
                    lambda s: s.partner_id == vendor and (not s.company_id or s.company_id == self.env.company)
                ).sorted(key=lambda s: s.price)

                # If a vendor-specific price exists, use it.
                # Otherwise, fallback to the requisition line price (Internal Cost).
                actual_price = seller[0].price if seller else line.unit_price
                # --- PRICE LOGIC END ---

                po_lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                    'product_uom': line.product_id.uom_po_id.id,
                    'price_unit': actual_price,
                }))

            po = PurchaseOrder.create({
                'partner_id': vendor.id,
                'origin': self.name,
                'order_line': po_lines,
            })
            po_records |= po

        # Link all created POs to this requisition
        self.purchase_order_ids = [(6, 0, po_records.ids)]
        self.state = 'done'

        # Redirect Logic (Form if 1, List if many)
        if len(po_records) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Purchase Order'),
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': po_records.id,
                'target': 'current',
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Purchase Orders'),
                'res_model': 'purchase.order',
                'view_mode': 'list,form',
                'domain': [('id', 'in', po_records.ids)],
                'target': 'current',
            }

    # --- Helper Methods ---
    def _is_department_manager(self):
        return self.env.user.employee_id == self.employee_id.department_id.manager_id

    def _is_job_title(self, title):
        job_name = self.env.user.employee_id.job_id.name
        return job_name.strip().lower() == title.lower() if job_name else False

    def _is_cfo(self):
        return self._is_job_title('chief financial officer')

    def _is_ceo(self):
        return self._is_job_title('chief executive officer')

    def _get_manager(self):
        return self.employee_id.parent_id or self.employee_id.department_id.manager_id

    def _get_employee_by_job(self, job_title):
        """Find an employee with a specific job title"""
        job = self.env['hr.job'].search([
            ('name', 'ilike', job_title)
        ], limit=1)
        if job:
            employee = self.env['hr.employee'].search([
                ('job_id', '=', job.id)
            ], limit=1)
            return employee
        return False

    def _create_activity(self, employee, summary):
        if employee.user_id:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=employee.user_id.id, summary=summary)

    def _clear_activities(self):
        self.activity_unlink(['mail.mail_activity_data_todo'])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                # Use sudo() to ensure sequence generation works for all users
                sequence = self.env['ir.sequence'].sudo().next_by_code('employee.requisition')
                vals['name'] = sequence or 'New'
        return super().create(vals_list)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    is_backup_approver = fields.Boolean(string="Backup Approver")


# FIX: Add the field to hr.employee.public as well
class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'
    is_backup_approver = fields.Boolean(string="Backup Approver", readonly=True)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_confirm(self):
        res = super(PurchaseOrder, self).button_confirm()

        for order in self:
            if not order.origin:
                continue

            # Find the related requisition
            requisition = self.env['employee.requisition'].search([
                ('name', '=', order.origin)
            ], limit=1)

            if requisition:
                # 1. Get the list of products in the PO we just confirmed
                confirmed_product_ids = order.order_line.mapped('product_id').ids

                # 2. Find "Duplicate" RFQs
                # These are RFQs for the same Requisition that contain the same products
                other_orders = requisition.purchase_order_ids.filtered(
                    lambda po: po.id != order.id and po.state in ['draft', 'sent']
                )

                for other_po in other_orders:
                    # Check if this other PO contains any of the products we just bought
                    other_po_products = other_po.order_line.mapped('product_id').ids

                    # If there is an overlap (intersection), cancel the other PO
                    if any(p_id in confirmed_product_ids for p_id in other_po_products):
                        other_po.button_cancel()
                        # Log why it was canceled for transparency
                        other_po.message_post(body=_(
                            "Canceled because a competing RFQ for the same items was confirmed: %s") % order.name)

                # 3. Update Requisition state only if ALL original items are now covered
                # (Optional: Only set to 'done' if no draft RFQs remain)
                remaining_rfqs = requisition.purchase_order_ids.filtered(lambda po: po.state in ['draft', 'sent'])
                if not remaining_rfqs:
                    requisition.state = 'done'

        return res