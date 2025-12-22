import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class VetAnimalVisit(models.Model):
    _name = "vet.animal.visit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Animal Visit"
    _order = "date desc"
    _rec_name = "name"

    company_id = fields.Many2one(
            'res.company',
            string='Branch',
            default=lambda self: self.env.company,
            required=True,
            readonly=True,
            ondelete='restrict'
            )

    name = fields.Char(string="Visit Reference", readonly=True, copy=False, default=lambda self: _("New"))
    date = fields.Datetime(default=fields.Datetime.now)
    animal_id = fields.Many2one("vet.animal", string="Animal", required=True, readonly=True)
    selected_animal_id = fields.Many2one('vet.animal', string="Select Animal", required=True)
    animal_ids = fields.Many2many('vet.animal', compute='_compute_animals_for_owner', string="Owner's Animals")
    animal_name = fields.Many2one('vet.animal', string="Animal Name")
    animal_display_name = fields.Char(string="Animal Name", compute="_compute_animal_display_name", store=True)
    animal_pic = fields.Image(string="Animal Picture", related='animal_id.image_1920', store=True, readonly=False)
    debug_animal_pic = fields.Char(compute="_compute_debug_animal_pic")
    owner_id = fields.Many2one('vet.animal.owner', string="Owner")
    contact_number = fields.Char(string="Owner Contact")
    doctor_id = fields.Many2one("vet.animal.doctor", string="Doctor", required=True, domain="[('company_id', '=', company_id)]")
    notes = fields.Text("Notes")
    treatment_charge = fields.Float(default=0.0)
    discount_percent = fields.Float(string="Discount (%)", default=0.0)
    discount_fixed = fields.Float(string="Discount (Fixed)", default=0.0)
    subtotal = fields.Float(compute="_compute_totals", store=True)
    total_amount = fields.Float(compute='_compute_totals', store=True)
    journal_id = fields.Many2one(
        'account.journal',
        string="Payment Journal",
        domain="[('company_id', '=', company_id), ('type', 'in', ['cash', 'bank'])]",
        help="Select the journal for payment"
    )

    is_fully_paid = fields.Boolean(
            string="Fully Paid",
            compute="_compute_is_fully_paid",
            store=False
            )
    line_ids = fields.One2many('vet.animal.visit.line', 'visit_id', string="Visit Lines")
    medicine_line_ids = fields.One2many(
            'vet.animal.visit.line', 'visit_id',
            domain=[('service_id.service_type', '=', 'vaccine')],
            string="Medicine Lines"
            )
    service_line_ids = fields.One2many(
            'vet.animal.visit.line', 'visit_id',
            domain=[('service_id.service_type', '=', 'service')],
            string="Service Lines"
            )
    test_line_ids = fields.One2many(
            'vet.animal.visit.line', 'visit_id',
            domain=[('service_id.service_type', '=', 'test')],
            string="Test Lines"
            )
    receipt_lines = fields.One2many(
            'vet.animal.visit.line', 'visit_id',
            compute='_compute_receipt_lines',
            string="Receipt Lines"
            )
    invoice_ids = fields.One2many('account.move', 'visit_id', string="Invoices")
    payment_state = fields.Selection(
            [('not_paid', 'Not Paid'), ('partial', 'Partially Paid'), ('paid', 'Paid')],
            string="Payment Status", compute="_compute_payment_state", store=True
            )
    has_unpaid_invoice = fields.Boolean(
            string="Has Unpaid Invoice",
            compute="_compute_has_unpaid_invoice",
            store=True
            )
    state = fields.Selection(
            [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('done', 'Done'), ('cancel', 'Cancelled')],
            default='draft'
            )
    delivered = fields.Boolean(default=False, string="Products Delivered")
    amount_received = fields.Float(compute='_compute_amount_received')
    latest_payment_amount = fields.Float(
            string="Latest Payment Amount",
            default=0.0,
            help="Amount of the most recent payment made for this visit."
            )
    owner_unpaid_balance = fields.Float(
            string="Unpaid Balance",
            compute="_compute_owner_unpaid_balance",
            store=False,
            digits=(16, 2),
            )
 
    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Filter doctors and journals when branch/company changes"""
        if self.company_id:
            if self.doctor_id and self.doctor_id.company_id != self.company_id:
                self.doctor_id = False
            
            if self.journal_id and self.journal_id.company_id != self.company_id:
                self.journal_id = False
            
            return {
                'domain': {
                    'doctor_id': [('company_id', '=', self.company_id.id)],
                    'journal_id': [('company_id', '=', self.company_id.id), ('type', 'in', ['cash', 'bank'])]
                }
            }
        else:
            return {
                'domain': {
                    'doctor_id': [('id', '!=', False)],
                    'journal_id': [('type', 'in', ['cash', 'bank'])]
                }
            }

    @api.depends('latest_payment_amount', 'invoice_ids', 'invoice_ids.state', 'invoice_ids.amount_residual')
    def _compute_amount_received(self):
        for visit in self:
            visit.amount_received = visit.latest_payment_amount or 0.0

    @api.depends('owner_id.partner_id')
    def _compute_has_unpaid_invoice(self):
        AccountMove = self.env['account.move']
        for visit in self:
            has_unpaid = False
            partner = visit.owner_id.partner_id
            if partner:
                unpaid = AccountMove.search_count([
                    ('partner_id', '=', partner.id),
                    ('move_type', '=', 'out_invoice'),
                    ('payment_state', 'in', ['not_paid', 'partial']),
                    ])
                has_unpaid = unpaid > 0
            visit.has_unpaid_invoice = has_unpaid

    @api.depends('payment_state')
    def _compute_is_fully_paid(self):
        for visit in self:
            visit.is_fully_paid = visit.payment_state == 'paid'

    @api.depends('animal_id', 'animal_id.image_1920')
    def _compute_debug_animal_pic(self):
        for rec in self:
            if rec.animal_id:
                _logger.info(
                        "VetAnimalVisit[%s]: animal_id=%s, image_1920 exists=%s, animal_pic exists=%s",
                        rec.id,
                        rec.animal_id.name,
                        bool(rec.animal_id.image_1920),
                        bool(rec.animal_pic)
                        )
                rec.debug_animal_pic = str(bool(rec.animal_pic))
            else:
                _logger.warning("VetAnimalVisit[%s]: No animal_id set", rec.id)
                rec.debug_animal_pic = "No animal_id"

    @api.depends('animal_id.image_1920')
    def _compute_animal_pic(self):
        for rec in self:
            rec.animal_pic = rec.animal_id.image_1920 or False

    @api.depends("animal_id")
    def _compute_animal_display_name(self):
        for record in self:
            record.animal_display_name = record.animal_id.name if record.animal_id else ""

    @api.depends('owner_id', 'contact_number')
    def _compute_animals_for_owner(self):
        for record in self:
            if record.owner_id:
                animals = self.env['vet.animal'].search([('owner_id', '=', record.owner_id.id)])
            elif record.contact_number:
                partners = self.env['res.partner'].search([('phone', '=', record.contact_number)])
                animals = self.env['vet.animal'].search([('owner_id', 'in', partners.ids)]) if partners else self.env['vet.animal'].browse()
            else:
                animals = self.env['vet.animal'].browse()
            record.animal_ids = animals

    @api.depends(
            'service_line_ids.subtotal',
            'test_line_ids.subtotal',
            'medicine_line_ids.subtotal',
            'treatment_charge',
            'discount_percent',
            'discount_fixed'
            )
    def _compute_totals(self):
        for visit in self:
            lines_total = sum(
                    l.subtotal for l in
                    (visit.service_line_ids + visit.test_line_ids + visit.medicine_line_ids)
                    )
            visit.subtotal = lines_total

            total = lines_total + (visit.treatment_charge or 0.0)

            if visit.discount_percent:
                total *= (1 - visit.discount_percent / 100)

            total -= visit.discount_fixed or 0.0

            visit.total_amount = max(total, 0.0)

    @api.depends(
            'service_line_ids.subtotal',
            'test_line_ids.subtotal',
            'medicine_line_ids.subtotal'
            )
    def _compute_receipt_lines(self):
        for visit in self:
            all_lines = (visit.service_line_ids +
                         visit.test_line_ids +
                         visit.medicine_line_ids)
            visit.receipt_lines = all_lines.filtered(
                    lambda l: l.quantity > 0 and l.product_id and l.price_unit > 0
                    )

    @api.depends('invoice_ids.payment_state')
    def _compute_payment_state(self):
        for visit in self:
            if not visit.invoice_ids:
                visit.payment_state = 'not_paid'
            else:
                total_amount = sum(visit.invoice_ids.mapped('amount_total'))
                residual_amount = sum(visit.invoice_ids.mapped('amount_residual'))
                if residual_amount == 0 and total_amount > 0:
                    visit.payment_state = 'paid'
                elif residual_amount < total_amount and residual_amount > 0:
                    visit.payment_state = 'partial'
                else:
                    visit.payment_state = 'not_paid'
            old_state = visit.state
            new_state = visit.state
            if old_state == 'cancel':
                continue
            if visit.payment_state == 'paid':
                new_state = 'done'
            elif visit.invoice_ids:
                new_state = 'confirmed'
            else:
                new_state = 'draft'
            if new_state != old_state:
                visit.with_context(skip_visit_validation=True).write({'state': new_state})

    @api.depends("owner_id")
    def _compute_owner_unpaid_balance(self):
        for visit in self:
            visit.owner_unpaid_balance = visit._get_owner_unpaid_balance()

    def action_confirm(self):
        for visit in self:
            if visit.state == 'draft':
                visit.with_context(skip_visit_validation=True).write({'state': 'confirmed'})
                visit.message_post(body=_("Visit confirmed."))

    def action_cancel(self):
        for visit in self:
            if visit.state in ['draft', 'confirmed']:
                if visit.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
                    raise UserError(_("Cannot cancel a visit with posted invoices. Please cancel the invoices first."))
                visit.with_context(skip_visit_validation=True).write({'state': 'cancel'})
                visit.message_post(body=_("Visit cancelled."))

    @api.model
    def create(self, vals):
        if not vals.get('animal_id') and vals.get('selected_animal_id'):
            vals['animal_id'] = vals['selected_animal_id']
        
        if not vals.get('animal_id'):
            raise ValidationError(
                _("Please select an animal before creating the visit.")
            )
        
        if 'doctor_id' in vals and vals['doctor_id']:
            company_id = vals.get('company_id') or self.env.company.id
            doctor = self.env['vet.animal.doctor'].browse(vals['doctor_id'])
            
            if doctor.company_id.id != company_id:
                company = self.env['res.company'].browse(company_id)
                raise ValidationError(
                    _("Doctor '%s' does not belong to branch '%s'. "
                      "Please select a doctor from the current branch.") 
                    % (doctor.name, company.name)
                )
        
        if vals.get("name", _("New")) == _("New"):
            company_id = vals.get('company_id') or self.env.company.id
            company = self.env['res.company'].browse(company_id)
            
            branch_code = company.branch_code
            if not branch_code:
                raise ValidationError(
                    _("Branch '%s' does not have a Branch Code configured. "
                      "Please set a Branch Code in Company settings before creating visits.") % company.name
                )
            
            sequence_code = f"vet.animal.visit.{branch_code.lower()}"
            
            sequence = self.env['ir.sequence'].search([
                ('code', '=', sequence_code),
                ('company_id', '=', company_id)
            ], limit=1)
            
            if not sequence:
                sequence = self.env['ir.sequence'].sudo().create({
                    'name': f'Vet Visit - {branch_code}',
                    'code': sequence_code,
                    'implementation': 'standard',
                    'prefix': f'VISIT-{branch_code}-',
                    'padding': 5,
                    'number_increment': 1,
                    'number_next': 1,
                    'company_id': company_id,
                })
                _logger.info("Created new visit sequence for branch %s: %s", branch_code, sequence_code)
            
            vals["name"] = sequence.next_by_id()
            _logger.info("Generated visit number: %s for branch: %s", vals["name"], branch_code)
        
        vals['company_id'] = vals.get('company_id') or self.env.company.id
        return super().create(vals)


    def write(self, vals):
        if self.env.context.get('skip_visit_validation') or self.env.context.get('from_payment_wizard'):
            return super().write(vals)
        if set(vals.keys()).issubset(['is_fully_paid', 'notes', 'latest_payment_amount']):
            return super().write(vals)
        
        if 'company_id' in vals and any(rec.company_id.id != vals['company_id'] for rec in self if rec.company_id):
            raise UserError(_("You cannot change the branch of an existing visit."))
        
        if 'doctor_id' in vals and vals['doctor_id']:
            for visit in self:
                company_id = vals.get('company_id', visit.company_id.id)
                doctor = self.env['vet.animal.doctor'].browse(vals['doctor_id'])
                
                if doctor.company_id.id != company_id:
                    raise ValidationError(
                        _("Doctor '%s' does not belong to branch '%s'. "
                          "Please select a doctor from the current branch.") 
                        % (doctor.name, visit.company_id.name)
                    )
        for visit in self:
            if visit.state in ['confirmed', 'done']:
                allowed_fields = ['notes', 'latest_payment_amount']
                restricted_fields = [key for key in vals.keys() if key not in allowed_fields]
                final_restricted_fields = []
                for key in restricted_fields:
                    field = visit._fields.get(key)
                    if field and field.compute and not field.store:
                        continue
                    final_restricted_fields.append(key)
                if 'state' in final_restricted_fields:
                    new_state = vals.get('state')
                    if visit.state == 'confirmed' and new_state in ['done', 'cancel']:
                        if new_state == 'done' and visit.payment_state != 'paid':
                            raise UserError(
                                    _("Cannot set visit %s to 'done' unless payment state is 'paid'.") % visit.name
                                    )
                        if new_state == 'cancel' and visit.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
                            raise UserError(
                                    _("Cannot cancel visit %s with posted invoices. Please cancel the invoices first.") % visit.name
                                    )
                        final_restricted_fields.remove('state')
                    else:
                        raise UserError(
                                _("Invalid state transition for visit %s from %s to %s.") % (
                                    visit.name, visit.state, new_state
                                    )
                                )
                receipt_related_fields = [
                        'line_ids', 'service_line_ids', 'test_line_ids', 'medicine_line_ids',
                        'treatment_charge', 'discount_percent', 'discount_fixed'
                        ]
                receipt_fields_attempted = [key for key in final_restricted_fields if key in receipt_related_fields]
                other_restricted_fields = [key for key in final_restricted_fields if key not in receipt_related_fields]
                if receipt_fields_attempted:
                    raise UserError(
                            _("Cannot modify receipt-related fields for visit %s in %s state. "
                              "Receipt fields attempted: %s. Only %s can be updated.") % (
                                  visit.name, visit.state, ', '.join(receipt_fields_attempted),
                                  ', '.join(allowed_fields) or 'no fields'
                                  )
                              )
                if other_restricted_fields:
                    raise UserError(
                            _("Cannot modify visit %s in %s state. "
                              "Non-receipt fields attempted: %s. Only %s can be updated.") % (
                                  visit.name, visit.state, ', '.join(other_restricted_fields),
                                  ', '.join(allowed_fields) or 'no fields'
                                  )
                              )
        return super().write(vals)

    def print_visit_receipt(self):
        return self.env.ref('vet_test.action_report_visit_receipt').report_action(self)

    @api.onchange('owner_id')
    def _onchange_owner_id(self):
        """Enhanced to auto-select animal if owner has only one"""
        domain = {'animal_id': [], 'selected_animal_id': []}
        
        if self.owner_id:
            self.contact_number = self.owner_id.contact_number or ''
            animals = self.env['vet.animal'].search([('owner_id', '=', self.owner_id.id)])
            
            if len(animals) == 1:
                self.selected_animal_id = animals[0]
                self.animal_id = animals[0]
                self.animal_name = animals[0]
                _logger.info("Visit: Auto-selected single animal %s for owner %s", 
                            animals[0].name, self.owner_id.name)
            elif len(animals) > 1:
                if self.selected_animal_id and self.selected_animal_id not in animals:
                    self.selected_animal_id = False
                    self.animal_id = False
                    self.animal_name = False
            else:
                self.selected_animal_id = False
                self.animal_id = False
                self.animal_name = False
            
            domain = {
                'animal_id': [('owner_id', '=', self.owner_id.id)],
                'selected_animal_id': [('owner_id', '=', self.owner_id.id)]
            }
        else:
            if not self.env.context.get('preserve_owner_context'):
                self.contact_number = ''
                self.selected_animal_id = False
                self.animal_id = False
                self.animal_name = False
            domain = {
                'animal_id': [('id', '!=', False)],
                'selected_animal_id': [('id', '!=', False)]
            }
        
        return {'domain': domain}

    @api.onchange('contact_number')
    def _onchange_contact_number(self):
        """Enhanced to preserve context for new animal creation"""
        if not self.contact_number:
            return {
                'domain': {
                    'animal_id': [('id', '!=', False)],
                    'selected_animal_id': [('id', '!=', False)]
                }
            }
        
        owner = self.env['vet.animal.owner'].search(
            [('contact_number', '=', self.contact_number.strip())], 
            limit=1
        )
        
        if owner:
            self.owner_id = owner
            animals = self.env['vet.animal'].search([('owner_id', '=', owner.id)])
            
            if len(animals) == 1:
                self.selected_animal_id = animals[0]
                self.animal_id = animals[0]
                self.animal_name = animals[0]
                _logger.info("Visit: Auto-selected single animal %s for contact %s", 
                            animals[0].name, self.contact_number)
            elif len(animals) > 1:
                self.selected_animal_id = False
                self.animal_id = False
                self.animal_name = False
            
            domain = {
                'animal_id': [('owner_id', '=', owner.id)],
                'selected_animal_id': [('owner_id', '=', owner.id)]
            }
        else:
            self.selected_animal_id = False
            self.animal_id = False
            self.animal_name = False
            domain = {
                'animal_id': [('id', '!=', False)],
                'selected_animal_id': [('id', '!=', False)]
            }
        
        return {'domain': domain}

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Filter doctors when branch/company changes"""
        if self.company_id:
            if self.doctor_id and self.doctor_id.company_id != self.company_id:
                self.doctor_id = False
            
            return {
                'domain': {
                    'doctor_id': [('company_id', '=', self.company_id.id)]
                }
            }
        else:
            return {
                'domain': {
                    'doctor_id': [('id', '!=', False)]
                }
            }

    def action_print_visit_receipt(self):
        self.ensure_one()
        if not self.exists():
            raise UserError(_("This visit record no longer exists."))
        _logger.info("Printing visit receipt - visit id=%s name=%s for user=%s", self.id, self.name, self.env.uid)
        return self.env.ref("vet_test.action_report_visit_receipt").report_action(self)

    def print_visit_receipt(self):
        self.ensure_one()
        if not self.exists():
            raise UserError(_("This visit record no longer exists."))

        if not self.contact_number:
            self.contact_number = self.owner_id.contact_number or ''

        _logger.info("🚨 PRINTING YOUR CUSTOM RECEIPT - visit=%s", self.name)
        return self.env.ref('vet_test.action_report_visit_receipt').report_action(self)

    def action_print_receipt(self):
        self.ensure_one()
        if not self.exists():
            raise UserError(_("This visit record no longer exists."))

        if not self.contact_number:
            self.contact_number = self.owner_id.contact_number or ''

        _logger.info("🚨 PRINTING YOUR CUSTOM RECEIPT - visit=%s", self.name)
        return self.env.ref('vet_test.action_report_visit_receipt').report_action(self)

    def _sync_state_with_payment(self):
        for visit in self:
            if visit.state == "cancel":
                continue
            new_state = 'draft'
            if visit.payment_state == "paid":
                new_state = "done"
            elif visit.invoice_ids:
                new_state = "confirmed"
            else:
                new_state = 'draft'

            if new_state != visit.state:
                visit.with_context(skip_visit_validation=True).write({'state': new_state})
                _logger.info("Visit %s: State synced to %s (payment_state=%s)",
                             visit.name, new_state, visit.payment_state)

    @api.constrains('payment_state', 'state')
    def _constrain_payment_state(self):
        for visit in self:
            if visit.state not in ['draft', 'cancel']:
                expected_state = 'done' if visit.payment_state == 'paid' else 'confirmed'
                if visit.state != expected_state:
                    visit.with_context(skip_visit_validation=True).write({'state': expected_state})
                    _logger.info("Visit %s: Constrained state to %s due to payment_state=%s",
                                 visit.name, expected_state, visit.payment_state)

    def _get_owner_unpaid_balance(self, exclude_visits=None):
        self.ensure_one()
        if not self.owner_id or not self.owner_id.partner_id:
            _logger.info("Visit %s: No owner_id or partner_id found, returning 0.0", self.name)
            return 0.0

        self.env["account.move"].invalidate_model(["amount_residual", "payment_state"])

        domain = [
                ("partner_id", "=", self.owner_id.partner_id.id),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "in", ["not_paid", "partial"]),
                ]

        if exclude_visits:
            domain.append(("visit_id", "not in", exclude_visits))

        invoices = self.env["account.move"].search(domain)
        balance = sum(invoices.mapped('amount_residual'))
        _logger.info("Visit %s: Calculated unpaid balance: %s for invoices %s",
                     self.name, balance, invoices.mapped('name'))
        return balance

    def _get_or_create_partner_from_owner(self, owner):
        if owner.partner_id:
            return owner.partner_id
        partner = self.env['res.partner'].create({
            'name': owner.name,
            'phone': owner.contact_number,
            'email': owner.email,
            })
        owner.partner_id = partner.id
        return partner

    @api.constrains('discount_percent', 'discount_fixed')
    def _check_discount_conflict(self):
        for visit in self:
            if visit.discount_percent > 0 and visit.discount_fixed > 0:
                raise ValidationError(
                        _("You cannot use both Discount (%) and Discount (Fixed) at the same time. Please use only one."))

    def action_create_invoice(self):
        for visit in self:
            if visit.invoice_ids:
                raise UserError(_("An invoice already exists for this visit."))
            if not visit.owner_id:
                raise UserError(_("Please set an owner before creating an invoice."))

            _logger.info("=" * 80)
            _logger.info("INVOICE: Starting invoice creation for visit %s", visit.name)
            _logger.info("=" * 80)

            # Step 1: AUTO-SELECT COMBO COMPONENTS
            test_lines_with_combos = visit.test_line_ids.filtered(
                lambda l: l.service_id and 
                l.service_id.service_type == 'test' and
                l.service_id.product_id and
                l.service_id.product_id.product_tmpl_id.type == 'combo'
            )
            
            _logger.info("Found %d test lines with combo products", len(test_lines_with_combos))
            
            # Collect component products to deliver
            components_to_deliver = []  # List of (product_id, quantity, service_id)
            
            if test_lines_with_combos:
                # Remove old component lines first
                old_component_lines = visit.test_line_ids.filtered(
                    lambda l: l.product_id and 
                    l.product_id.type in ('product', 'consu') and
                    l.service_id and 
                    l.service_id.service_type == 'test'
                )
                if old_component_lines:
                    old_component_lines.unlink()
                    _logger.info("Removed %d old component lines", len(old_component_lines))
                
                # Process each combo test line
                for test_line in test_lines_with_combos:
                    service = test_line.service_id
                    product = service.product_id
                    combo_choices = product.product_tmpl_id.combo_ids
                    
                    _logger.info("Processing combo test: %s with %d combo choices", 
                                product.name, len(combo_choices))
                    
                    for combo in combo_choices:
                        if combo.combo_item_ids:
                            # Process ALL components in the combo, not just the first
                            for combo_item in combo.combo_item_ids:
                                component = combo_item.product_id
                                
                                _logger.info("  Selected component: %s (type: %s)", 
                                            component.name, component.type)
                                
                                # Only stockable products need delivery
                                if component.type in ('product', 'consu'):
                                    qty = test_line.quantity * 1.0
                                    components_to_deliver.append((component.id, qty, service.id))
                                    
                                    # Also create visit line for tracking
                                    self.env['vet.animal.visit.line'].create({
                                        'visit_id': visit.id,
                                        'service_id': service.id,
                                        'product_id': component.id,
                                        'quantity': qty,
                                        'price_unit': 0.0,
                                        'delivered': False,
                                    })
                                    _logger.info("  Added to delivery: %s qty=%s", component.name, qty)

            # Step 2: Collect all stockable items (vaccines + test components)
            all_stockable = []
            
            # Add vaccines
            for med_line in visit.medicine_line_ids:
                if (med_line.product_id and 
                    med_line.product_id.type in ('product', 'consu') and 
                    med_line.quantity > 0 and 
                    not med_line.delivered):
                    all_stockable.append((med_line.product_id.id, med_line.quantity, med_line.service_id.id if med_line.service_id else False))
                    _logger.info("Added vaccine to delivery: %s qty=%s", med_line.product_id.name, med_line.quantity)
            
            # Add test components we just selected
            all_stockable.extend(components_to_deliver)
            
            _logger.info("Total items to deliver: %d", len(all_stockable))

            # Step 3: Check stock availability
            if all_stockable:
                warehouse = self.env.user._get_default_warehouse_id()
                if not warehouse or not warehouse.lot_stock_id:
                    raise UserError(_("Please configure a default warehouse with a stock location."))
                
                required = {}
                for prod_id, qty, service_id in all_stockable:
                    required[prod_id] = required.get(prod_id, 0.0) + qty
                
                products = self.env['product.product'].browse(required.keys()).with_context(
                    location=warehouse.lot_stock_id.id
                )
                
                errors = []
                for prod in products:
                    if required[prod.id] > prod.qty_available:
                        errors.append(_("- %s: need %.2f, only %.2f on hand") % 
                                    (prod.display_name, required[prod.id], prod.qty_available))
                if errors:
                    raise UserError(_("Insufficient stock:\n%s") % "\n".join(errors))

            # Step 4: Create Invoice
            partner = visit._get_or_create_partner_from_owner(visit.owner_id)
            if not partner:
                raise UserError(_("Could not create a partner for the owner."))

            # Get invoiceable lines (exclude stockable test components)
            all_lines = visit.service_line_ids + visit.test_line_ids + visit.medicine_line_ids
            invoiceable_lines = all_lines.filtered(
                lambda l: l.product_id and 
                l.quantity > 0 and 
                l.price_unit > 0 and
                not (l.service_id and 
                     l.service_id.service_type == 'test' and 
                     l.product_id.type in ('product', 'consu'))
            )
            
            _logger.info("Creating invoice with %d invoiceable lines", len(invoiceable_lines))

            invoice_lines = []
            Account = self.env['account.account']
            income_account = Account.search([('account_type', '=', 'income')], limit=1) or \
                    Account.search([('user_type_id.type', '=', 'income')], limit=1)
            first_account_id = income_account.id if income_account else False

            def _get_income_account(product):
                tmpl = product.product_tmpl_id
                return (product.property_account_income_id.id or
                        (tmpl.property_account_income_id.id if tmpl.property_account_income_id else None) or
                        (tmpl.categ_id.property_account_income_categ_id.id if tmpl.categ_id else None))

            discount_percent = visit.discount_percent

            for line in invoiceable_lines:
                prod = line.product_id
                account_id = _get_income_account(prod) or first_account_id
                if not account_id:
                    raise UserError(_("No income account for %s") % prod.display_name)
                if not first_account_id:
                    first_account_id = account_id

                invoice_lines.append((0, 0, {
                    'product_id': prod.id,
                    'name': prod.display_name,
                    'quantity': line.quantity,
                    'price_unit': line.price_unit,
                    'account_id': account_id,
                    'tax_ids': [(6, 0, prod.taxes_id.ids)],
                    'discount': discount_percent,
                }))

            if visit.treatment_charge > 0:
                invoice_lines.append((0, 0, {
                    'name': _("Treatment Charge"),
                    'quantity': 1.0,
                    'price_unit': visit.treatment_charge,
                    'account_id': first_account_id,
                    'tax_ids': [(6, 0, [])],
                    'discount': discount_percent,
                }))

            if visit.discount_fixed > 0:
                invoice_lines.append((0, 0, {
                    'name': _("Discount (Fixed)"),
                    'quantity': 1.0,
                    'price_unit': -visit.discount_fixed,
                    'account_id': first_account_id,
                    'tax_ids': [(6, 0, [])],
                }))

            if not invoice_lines:
                raise UserError(_("No invoiceable lines found."))

            invoice = self.env['account.move'].create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_line_ids': invoice_lines,
                'invoice_date': fields.Date.context_today(self),
                'invoice_origin': visit.name,
                'visit_id': visit.id,
            })

            missing = invoice.invoice_line_ids.filtered(lambda l: not l.account_id)
            if missing and invoice.invoice_line_ids[:1].account_id:
                missing.write({'account_id': invoice.invoice_line_ids[:1].account_id.id})

            invoice.action_post()
            _logger.info("Invoice %s posted successfully", invoice.name)
            
            visit.with_context(skip_visit_validation=True).write({'invoice_ids': [(4, invoice.id)]})

            # Step 5: Create Delivery Order DIRECTLY
            if all_stockable:
                _logger.info("=" * 80)
                _logger.info("DELIVERY: Creating delivery for %d items", len(all_stockable))
                _logger.info("=" * 80)
                
                try:
                    StockPicking = self.env['stock.picking']
                    StockMove = self.env['stock.move']
                    try:
                        StockLotModel = self.env['stock.lot']
                    except KeyError:
                        StockLotModel = self.env['stock.production.lot']

                    warehouse = self.env.user._get_default_warehouse_id()
                    picking_type = warehouse.out_type_id
                    dest_location = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
                    
                    if not dest_location:
                        raise UserError(_("The 'Customers' stock location could not be found."))

                    # Create picking
                    picking = StockPicking.create({
                        'picking_type_id': picking_type.id,
                        'location_id': warehouse.lot_stock_id.id,
                        'location_dest_id': dest_location.id,
                        'origin': f"Visit {visit.name}",
                        'partner_id': partner.id,
                    })
                    
                    _logger.info("Created picking: %s", picking.name)

                    # Create moves for each item
                    for prod_id, qty, service_id in all_stockable:
                        product = self.env['product.product'].browse(prod_id)
                        
                        move = StockMove.create({
                            'name': product.display_name,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': product.uom_id.id,
                            'picking_id': picking.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': picking.location_dest_id.id,
                        })
                        
                        _logger.info("Created move: %s (qty: %s)", product.name, qty)

                        # Create lot if needed
                        lot_id = False
                        if product.tracking in ('lot', 'serial'):
                            lot_name = f"{visit.name}-{product.default_code or product.id}-{uuid.uuid4().hex[:8]}"
                            lot = StockLotModel.create({
                                'name': lot_name,
                                'product_id': product.id,
                                'company_id': self.env.company.id,
                            })
                            lot_id = lot.id
                            _logger.info("Created lot: %s", lot_name)

                        # Create move line
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'product_uom_id': product.uom_id.id,
                            'quantity': qty,
                            'qty_done': qty,
                            'location_id': picking.location_id.id,
                            'location_dest_id': picking.location_dest_id.id,
                            'lot_id': lot_id,
                        })

                    # Validate picking
                    picking.action_confirm()
                    _logger.info("Picking confirmed")
                    
                    picking.action_assign()
                    _logger.info("Picking assigned")
                    
                    res = picking.button_validate()
                    _logger.info("Picking validation result: %s", res)
                    
                    if picking.state == 'done':
                        # Mark lines as delivered
                        delivered_line_ids = []
                        for prod_id, qty, service_id in all_stockable:
                            lines = visit.line_ids.filtered(
                                lambda l: l.product_id.id == prod_id and not l.delivered
                            )
                            delivered_line_ids.extend(lines.ids)
                        
                        if delivered_line_ids:
                            self.env['vet.animal.visit.line'].browse(delivered_line_ids).write({'delivered': True})
                        
                        visit.with_context(skip_visit_validation=True).write({'delivered': True})
                        _logger.info("Delivery completed successfully!")
                    else:
                        _logger.warning("Picking state is: %s", picking.state)

                except Exception as e:
                    _logger.error("Delivery creation failed: %s", str(e), exc_info=True)
                    raise UserError(_("Invoice created but delivery failed: %s") % str(e))
            
            visit.with_context(skip_visit_validation=True)._sync_state_with_payment()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success!'),
                    'message': _('Invoice %s created and products delivered successfully!') % invoice.name,
                    'type': 'success',
                    'sticky': False,
                }
            }

    def action_deliver_products(self):
        StockPicking = self.env['stock.picking']
        StockMove = self.env['stock.move']
        try:
            StockLotModel = self.env['stock.lot']
        except KeyError:
            StockLotModel = self.env['stock.production.lot']

        for visit in self:
            _logger.info("=" * 80)
            _logger.info("DELIVERY PROCESS START for visit: %s", visit.name)
            _logger.info("=" * 80)
            
            # Skip if already delivered
            if visit.delivered:
                _logger.info("Visit %s already delivered, skipping", visit.name)
                continue

            # Force refresh of all lines to get newly created component lines
            visit.invalidate_recordset(['line_ids', 'medicine_line_ids', 'test_line_ids'])
            
            # Get ALL lines that need delivery (vaccines + test components)
            _logger.info("Medicine lines count: %d", len(visit.medicine_line_ids))
            _logger.info("Test lines count: %d", len(visit.test_line_ids))
            
            for line in visit.medicine_line_ids:
                _logger.info("  Medicine line: %s, product=%s, type=%s, qty=%s, delivered=%s",
                            line.id, 
                            line.product_id.name if line.product_id else 'None',
                            line.product_id.type if line.product_id else 'N/A',
                            line.quantity,
                            line.delivered)
            
            for line in visit.test_line_ids:
                _logger.info("  Test line: %s, product=%s, type=%s, qty=%s, delivered=%s, service_type=%s",
                            line.id,
                            line.product_id.name if line.product_id else 'None',
                            line.product_id.type if line.product_id else 'N/A',
                            line.quantity,
                            line.delivered,
                            line.service_type if hasattr(line, 'service_type') else 'N/A')
            
            all_lines = visit.medicine_line_ids + visit.test_line_ids
            
            deliverable_lines = all_lines.filtered(
                lambda l: l.product_id
                and l.product_id.type in ('product', 'consu')
                and l.quantity > 0
                and not l.delivered
            )

            _logger.info("Found %d deliverable lines:", len(deliverable_lines))
            for line in deliverable_lines:
                _logger.info("  → Product: %s, Type: %s, Qty: %s, Service Type: %s, ID: %s",
                            line.product_id.name,
                            line.product_id.type,
                            line.quantity,
                            line.service_type if hasattr(line, 'service_type') else 'N/A',
                            line.id)

            if not deliverable_lines:
                visit.with_context(skip_visit_validation=True).write({'delivered': True})
                _logger.info("Visit %s: No stockable medicine/test lines to deliver", visit.name)
                continue

            # Warehouse / locations
            warehouse = self.env.user._get_default_warehouse_id()
            if not warehouse or not warehouse.out_type_id or not warehouse.lot_stock_id:
                raise UserError(
                    _("Please configure the default warehouse with an Outgoing Shipments type and a stock location.")
                )
            picking_type = warehouse.out_type_id
            dest_location = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
            if not dest_location:
                raise UserError(_("The 'Customers' stock location could not be found."))

            # STOCK AVAILABILITY CHECK
            required = {}
            for line in deliverable_lines:
                required[line.product_id.id] = required.get(line.product_id.id, 0.0) + line.quantity

            products = self.env['product.product'].browse(required.keys())
            products = products.with_context(location=warehouse.lot_stock_id.id)

            errors = []
            for prod in products:
                needed = required[prod.id]
                available = prod.qty_available
                _logger.info("Stock check: %s - need %.2f, have %.2f", prod.name, needed, available)
                if needed > available:
                    errors.append(
                        _("- %s: need %.2f, only %.2f on hand") % (prod.display_name, needed, available)
                    )
            if errors:
                raise UserError(
                    _("Insufficient stock in location **%s**:\n%s")
                    % (warehouse.lot_stock_id.complete_name, "\n".join(errors))
                )

            # CREATE PICKING
            picking = StockPicking.create({
                'picking_type_id': picking_type.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': dest_location.id,
                'origin': f"Visit {visit.name}",
                'partner_id': visit.owner_id and visit._get_or_create_partner_from_owner(visit.owner_id).id or False,
            })
            
            _logger.info("Created picking: %s", picking.name)

            for line in deliverable_lines:
                move = StockMove.create({
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
                
                _logger.info("Created move for: %s (qty: %s)", line.product_id.name, line.quantity)

                lot_id = False
                if line.product_id.tracking in ('lot', 'serial'):
                    lot_name = f"{visit.name}-{line.product_id.default_code or line.product_id.id}-{uuid.uuid4().hex[:8]}"
                    lot = StockLotModel.create({
                        'name': lot_name,
                        'product_id': line.product_id.id,
                        'company_id': self.env.company.id,
                    })
                    lot_id = lot.id
                    _logger.info("Created lot: %s", lot_name)

                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_id.uom_id.id,
                    'quantity': line.quantity,
                    'qty_done': line.quantity,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                    'lot_id': lot_id,
                })

            # VALIDATE PICKING
            try:
                picking.action_confirm()
                _logger.info("Picking confirmed")
                
                picking.action_assign()
                _logger.info("Picking assigned")
                
                res = picking.button_validate()
                _logger.info("Picking validation result: %s", res)
                
                if isinstance(res, dict):
                    _logger.warning("Visit %s: Backorder created for picking %s.", visit.name, picking.name)
                else:
                    _logger.info("Visit %s: Stock picking %s validated successfully.", visit.name, picking.name)

                if picking.state == 'done':
                    deliverable_lines.write({'delivered': True})
                    visit.with_context(skip_visit_validation=True).write({'delivered': True})
                    _logger.info("Visit %s: All product delivery processed successfully", visit.name)
                else:
                    _logger.warning("Picking state is: %s (expected 'done')", picking.state)
                    
            except Exception as e:
                picking.unlink()
                _logger.error("Visit %s: Failed to validate stock picking %s: %s", visit.name, picking.name, str(e))
                raise UserError(_("Failed to process delivery for visit %s: %s") % (visit.name, str(e)))

        return True

    def action_pay_invoice(self):
        self.ensure_one()
        if not self.invoice_ids:
            raise UserError(_("No invoice found for this visit."))

        invoices = self.invoice_ids.filtered(lambda inv: inv.payment_state in ["not_paid", "partial"])
        if not invoices:
            raise UserError(_("All invoices are already paid."))

        unpaid_balance = self._get_owner_unpaid_balance()

        return {
                "name": _("Register Payment"),
                "type": "ir.actions.act_window",
                "res_model": "vet.animal.visit.payment.wizard",
                "view_mode": "form",
                "target": "new",
                'context': {
                    "default_visit_id": self.id,
                    "default_owner_unpaid_balance": unpaid_balance,
                    "default_amount": unpaid_balance,
                    },
                }

    def action_view_invoices(self):
        self.ensure_one()
        if not self.invoice_ids:
            return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("No Invoices"),
                        'message': _("No invoices exist for this visit."),
                        'sticky': False
                        }
                    }
        return {
                'name': _("Invoices"),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'list,form',
                'views': [
                    (
                        self.env.ref('vet_test.view_vet_animal_visit_invoice_list').id, 'list'
                        ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_list', False) else (False, 'list'),
                    (
                        self.env.ref('vet_test.view_vet_animal_visit_invoice_form').id, 'form'
                        ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_form', False) else (False, 'form')
                    ],
                'domain': [('id', 'in', self.invoice_ids.ids)],
                'context': {'default_visit_id': self.id},
                }

    @api.onchange('owner_id')
    def _onchange_owner_selected_animals(self):
        if self.owner_id:
            return {'domain': {'selected_animal_id': [('owner_id', '=', self.owner_id.id)]}}
        return {'domain': {'selected_animal_id': []}}

    @api.onchange('selected_animal_id')
    def _onchange_selected_animal_id(self):
        """
        When user selects an animal:
        - Update the readonly animal_id field
        - Update related owner and contact info
        - Update animal_name for consistency
        """
        if self.selected_animal_id:
            self.animal_id = self.selected_animal_id
            self.animal_name = self.selected_animal_id
            
            self.owner_id = self.selected_animal_id.owner_id
            self.contact_number = self.selected_animal_id.owner_id.contact_number or ''
            
            self.animal_ids = self.env['vet.animal'].search([
                ('owner_id', '=', self.owner_id.id)
            ])
            
            _logger.info(
                "Visit: Selected animal changed to %s (ID: %s), Owner: %s", 
                self.selected_animal_id.name, 
                self.selected_animal_id.id,
                self.owner_id.name if self.owner_id else 'None'
            )
        else:
            self.animal_id = False
            self.animal_name = False
            
            if self.owner_id:
                self.animal_ids = self.env['vet.animal'].search([
                    ('owner_id', '=', self.owner_id.id)
                ])
            else:
                self.animal_ids = False

    def _onchange_animal_name(self):
        if self.animal_name:
            self.animal_id = self.animal_name
            self.selected_animal_id = self.animal_name
            self.owner_id = self.animal_name.owner_id
            self.contact_number = self.animal_name.owner_id.contact_number or ''
        else:
            self.animal_id = False
            self.selected_animal_id = False
            self.owner_id = False
            self.contact_number = ''

    def action_complete_payment(self):
        self.ensure_one()
        if not self.invoice_ids:
            raise UserError(_("No invoice found for this visit."))

        partner = self.owner_id.partner_id
        invoices = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ], order='invoice_date asc, id asc')

        if not invoices:
            raise UserError(_("No unpaid invoices found for this owner."))

        return {
                'name': _('Register Payment'),
                'type': 'ir.actions.act_window',
                'res_model': 'account.payment.register',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'active_model': 'account.move',
                    'active_ids': invoices.ids,
                    'default_partner_id': partner.id,
                    'default_amount': sum(invoices.mapped('amount_residual')),
                    'default_payment_type': 'inbound',
                    'default_partner_type': 'customer',
                    }
                }


class VetAnimal(models.Model):
    _inherit = "vet.animal"

    def name_get(self):
        result = []
        for animal in self:
            parts = []
            if animal.microchip_no:
                parts.append(f"#{animal.microchip_no}")
            if animal.name:
                parts.append(animal.name)
            if animal.owner_id:
                parts.append(f"Owner: {animal.owner_id.name}")
                if animal.owner_id.contact_number:   # ← FIXED: removed stray "d"
                    parts.append(f"Phone: {animal.owner_id.contact_number}")
            display = " | ".join(parts)
            result.append((animal.id, display))
        return result
    @api.model
    def default_get(self, fields_list):
        """Auto-populate owner from visit form context"""
        res = super().default_get(fields_list)

        contact_number = self.env.context.get('default_contact_number')
        owner_name = self.env.context.get('default_owner_name', 'New Owner')

        if contact_number:
            owner = self.env['vet.animal.owner'].search(
                    [('contact_number', '=', contact_number)], 
                    limit=1
                    )

            if not owner:
                owner = self.env['vet.animal.owner'].create({
                    'name': owner_name,
                    'contact_number': contact_number,
                    })
                _logger.info("Created new owner: %s with contact: %s", owner.name, contact_number)

            res['owner_id'] = owner.id
            _logger.info("Animal form pre-filled with owner_id: %s", owner.id)

        return res
    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        args = args or []
        name = (name or '').strip()
        if not name:
            return self.search(args, limit=limit).name_get()
        if name.startswith('#'):
            chip = name[1:].strip()
            domain = [('microchip_no', '=', chip)]
        else:
            domain = ['|', ('microchip_no', operator, name), ('name', operator, name)]
        try:
            records = self.search(domain + args, limit=limit)
            return records.name_get()
        except Exception as exc:
            _logger.exception("vet.animal.name_search failed: %s", exc)
            return []

    def action_view_invoices(self):
        self.ensure_one()
        return {
                'name': 'Invoices',
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'list,form',
                'views': [
                    (
                        self.env.ref('vet_test.view_vet_animal_visit_invoice_list').id, 'list'
                        ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_list', False) else (False, 'list'),
                    (
                        self.env.ref('vet_test.view_vet_animal_visit_invoice_form').id, 'form'
                        ) if self.env.ref('vet_test.view_vet_animal_visit_invoice_form', False) else (False, 'form')
                    ],
                'domain': [('visit_id', 'in', self.env['vet.animal.visit'].search([('animal_id', '=', self.id)]).ids),
                           ('payment_state', '!=', 'paid')],
                'context': {'create': False},
                }


class VetTestComboSelectionWizard(models.Model):
    _name = 'vet.test.combo.selection.wizard'
    _description = 'Select Components for Test Combo'

    visit_id = fields.Many2one('vet.animal.visit', string="Visit", readonly=True, required=True)
    test_line_ids = fields.Many2many('vet.animal.visit.line', string="Test Lines", readonly=True)
    line_ids = fields.One2many('vet.test.combo.selection.wizard.line', 'wizard_id', string="Components")

    test_line_id = fields.Many2one('vet.animal.visit.line', string="Test Line", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        context = self.env.context
        visit_id = context.get('default_visit_id')
        
        if visit_id:
            visit = self.env['vet.animal.visit'].browse(visit_id)
            test_line_ids = context.get('default_test_line_ids', [])
            test_lines = self.env['vet.animal.visit.line'].browse(test_line_ids)
            
            res.update({
                'visit_id': visit.id,
                'test_line_ids': [(6, 0, test_line_ids)],
            })

            wizard_lines = []
            
            for line in test_lines.filtered(lambda l: l.service_id):
                service = line.service_id
                product = service.product_id
                
                if not product or product.product_tmpl_id.type != 'combo':
                    _logger.warning("Test service %s has no combo product", service.name)
                    continue
                
                # Get combo choices for this test
                combo_choices = product.product_tmpl_id.combo_ids
                
                if not combo_choices:
                    _logger.warning("Test product %s has no combo choices", product.name)
                    continue
                
                # In Odoo 18, combo_ids contains product.combo records
                # Each combo has combo_item_ids which are the selectable products
                for combo in combo_choices:
                    for combo_item in combo.combo_item_ids:
                        component = combo_item.product_id
                        
                        # Each combo item has a default quantity of 1
                        item_qty = 1.0
                        
                        # Only add stockable products to wizard (for delivery)
                        if component.type in ('product', 'consu'):
                            wizard_lines.append((0, 0, {
                                'combo_product_id': product.id,
                                'component_product_id': component.id,
                                'quantity_to_deliver': line.quantity * item_qty,
                                'product_uom_id': component.uom_id.id,
                                'test_line_id': line.id,
                            }))
                            
                            _logger.info("Added combo component: %s (qty: %s) for test: %s", 
                                       component.name, 
                                       line.quantity * item_qty,
                                       product.name)
            
            res['line_ids'] = wizard_lines
            
        return res

    def action_process(self):
        """Process selected components and create invoice"""
        self.ensure_one()
        visit = self.visit_id
        
        _logger.info("=" * 80)
        _logger.info("WIZARD: Processing combo selection for visit %s", visit.name)
        _logger.info("=" * 80)
        
        old_component_lines = visit.test_line_ids.filtered(
            lambda l: l.product_id and 
            l.product_id.type in ('product', 'consu') and
            l.service_id and 
            l.service_id.service_type == 'test'
        )
        if old_component_lines:
            old_component_lines.unlink()
            _logger.info("Visit %s: Removed %d old test component lines", 
                        visit.name, len(old_component_lines))
        
        new_lines = []
        for wizard_line in self.line_ids:
            if wizard_line.quantity_to_deliver <= 0:
                _logger.warning("Skipping wizard line with zero quantity")
                continue
            
            test_line = wizard_line.test_line_id
            if not test_line or not test_line.service_id:
                _logger.warning("Wizard line missing test_line or service")
                continue
            
            # Create a line with the COMPONENT product (for delivery only)
            new_lines.append((0, 0, {
                'visit_id': visit.id,
                'service_id': test_line.service_id.id,
                'product_id': wizard_line.component_product_id.id,
                'quantity': wizard_line.quantity_to_deliver,
                'price_unit': 0.0,  # No price - not invoiced
                'delivered': False,
            }))
            
            _logger.info("WIZARD: Queuing component line: %s (qty: %s)", 
                        wizard_line.component_product_id.name,
                        wizard_line.quantity_to_deliver)
        
        created_line_ids = []
        
        if new_lines:
            visit.with_context(skip_visit_validation=True).write({
                'line_ids': new_lines
            })
            _logger.info("WIZARD: Created %d component lines", len(new_lines))
            
            visit.invalidate_recordset(['line_ids', 'test_line_ids'])
            
            test_components = visit.test_line_ids.filtered(
                lambda l: l.product_id and 
                l.product_id.type in ('product', 'consu') and
                not l.delivered
            )
            created_line_ids = test_components.ids
            
            _logger.info("WIZARD: After write, visit has %d test component lines", 
                        len(test_components))
            for line in test_components:
                _logger.info("  → %s: qty=%s, type=%s", 
                            line.product_id.name, 
                            line.quantity,
                            line.product_id.type)
        
        if self.line_ids:
            warehouse = self.env.user._get_default_warehouse_id()
            if not warehouse or not warehouse.lot_stock_id:
                raise UserError(_("Please configure a default warehouse with a stock location."))
            
            source_loc = warehouse.lot_stock_id
            required = {}
            for wizard_line in self.line_ids:
                if wizard_line.quantity_to_deliver > 0:
                    pid = wizard_line.component_product_id.id
                    required[pid] = required.get(pid, 0.0) + wizard_line.quantity_to_deliver
            
            products = self.env['product.product'].browse(required.keys()).with_context(location=source_loc.id)
            errors = []
            for prod in products:
                if required[prod.id] > prod.qty_available:
                    errors.append(_("- %s: need %.2f, only %.2f on hand") % (prod.display_name, required[prod.id], prod.qty_available))
            
            if errors:
                raise UserError(_("Insufficient stock:\n%s") % "\n".join(errors))
        
        warehouse = self.env.user._get_default_warehouse_id()
        if not warehouse or not warehouse.out_type_id or not warehouse.lot_stock_id:
            raise UserError(
                _("Please configure the default warehouse with an Outgoing Shipments type and a stock location.")
            )
        picking_type = warehouse.out_type_id
        dest_location = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
        if not dest_location:
            raise UserError(_("The 'Customers' stock location could not be found."))
        
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': dest_location.id,
            'origin': f"Visit {visit.name}",
            'partner_id': visit.owner_id and visit._get_or_create_partner_from_owner(visit.owner_id).id or False,
        })
        
        for wizard_line in self.line_ids:
            if wizard_line.quantity_to_deliver <= 0:
                continue
            
            move = self.env['stock.move'].create({
                'name': wizard_line.component_product_id.name,
                'product_id': wizard_line.component_product_id.id,
                'product_uom_qty': wizard_line.quantity_to_deliver,
                'product_uom': wizard_line.component_product_id.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
            
            _logger.info("Created move for: %s (qty: %s)", wizard_line.component_product_id.name, wizard_line.quantity_to_deliver)
            
            lot_id = False
            if wizard_line.component_product_id.tracking in ('lot', 'serial'):
                lot_name = f"{visit.name}-{wizard_line.component_product_id.default_code or wizard_line.component_product_id.id}-{uuid.uuid4().hex[:8]}"
                try:
                    StockLotModel = self.env['stock.lot']
                except KeyError:
                    StockLotModel = self.env['stock.production.lot']
                
                lot = StockLotModel.create({
                    'name': lot_name,
                    'product_id': wizard_line.component_product_id.id,
                    'company_id': self.env.company.id,
                })
                lot_id = lot.id
                _logger.info("Created lot: %s", lot_name)
            
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': wizard_line.component_product_id.id,
                'product_uom_id': wizard_line.component_product_id.uom_id.id,
                'quantity': wizard_line.quantity_to_deliver,
                'qty_done': wizard_line.quantity_to_deliver,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'lot_id': lot_id,
            })
        
        try:
            picking.action_confirm()
            _logger.info("Picking confirmed")
            
            picking.action_assign()
            _logger.info("Picking assigned")
            
            res = picking.button_validate()
            _logger.info("Picking validation result: %s", res)
            
            if isinstance(res, dict):
                _logger.warning("Visit %s: Backorder created for picking %s.", visit.name, picking.name)
            else:
                _logger.info("Visit %s: Stock picking %s validated successfully.", visit.name, picking.name)

            if picking.state == 'done':
                if created_line_ids:
                    component_lines = self.env['vet.animal.visit.line'].browse(created_line_ids)
                    component_lines.write({'delivered': True})
                    _logger.info("Visit %s: Marked %d component lines as delivered", visit.name, len(component_lines))
                
                all_stockable = visit.line_ids.filtered(
                    lambda l: l.product_id and l.product_id.type in ('product', 'consu')
                )
                all_delivered = all(line.delivered for line in all_stockable)
                
                if all_delivered:
                    visit.with_context(skip_visit_validation=True).write({'delivered': True})
                    _logger.info("Visit %s: All product delivery processed successfully", visit.name)
            else:
                _logger.warning("Picking state is: %s (expected 'done')", picking.state)
        
        except Exception as e:
            _logger.error("Error during picking validation: %s", e, exc_info=True)
            picking.unlink()
            raise UserError(_("An error occurred while processing the stock picking for the test components: %s") % str(e))
        
        _logger.info("WIZARD: Calling action_create_invoice with from_combo_wizard=True")
        return visit.with_context(from_combo_wizard=True).action_create_invoice()


class VetTestComboSelectionWizardLine(models.TransientModel):
    _name = 'vet.test.combo.selection.wizard.line'

    test_line_id = fields.Many2one('vet.animal.visit.line', string="Test Line")
    combo_product_id = fields.Many2one('product.product', string="Test/Combo", readonly=True)
    component_product_id = fields.Many2one('product.product', string="Component to Deliver", required=True)
    quantity_to_deliver = fields.Float(string="Quantity", required=True)
    product_uom_id = fields.Many2one('uom.uom', string="Unit of Measure", required=True)
    available_quantity = fields.Float(related='component_product_id.qty_available', string="On Hand")
    wizard_id = fields.Many2one('vet.test.combo.selection.wizard', string="Wizard")

    @api.model
    def create(self, vals):
        if 'product_uom_id' not in vals:
            if 'component_product_id' in vals:
                product = self.env['product.product'].browse(vals['component_product_id'])
                vals['product_uom_id'] = product.uom_id.id  # Set default UoM from the component product
        
        return super(VetTestComboSelectionWizardLine, self).create(vals)

class VetAnimalVisitPaymentWizard(models.Model):
    _name = "vet.animal.visit.payment.wizard"
    _description = "Vet Animal Visit Payment Wizard"

    journal_id = fields.Many2one(
        "account.journal",
        string="Payment Journal",
        domain="[('company_id', '=', company_id), ('type', 'in', ['cash', 'bank'])]",
        required=True,
        help="Select the payment journal (Cash or Bank) for this branch"
    )
    company_id = fields.Many2one(
        'res.company',
        string='Branch',
        related='visit_id.company_id',
        store=True,
        readonly=True
    )
    amount = fields.Float(
        string="Payment Amount",
        required=True
    )
    visit_id = fields.Many2one(
        'vet.animal.visit',
        string="Visit",
        required=True
    )
    current_invoice_id = fields.Many2one(
        'account.move',
        string="Current Invoice",
        compute="_compute_current_invoice",
        store=False
    )
    current_invoice_amount = fields.Float(
        string="Current Invoice Amount",
        compute="_compute_current_invoice",
        store=False
    )
    payment_mode = fields.Selection([
        ('current', 'Pay Current Invoice Only'),
        ('other', 'Pay Other Invoices'),
        ('all', 'Pay All Unpaid Invoices')
    ], string="Payment Mode", default='current', required=True)
    
    other_invoice_ids = fields.Many2many(
        'account.move',
        'wizard_invoice_rel',
        'wizard_id',
        'invoice_id',
        string="Select Other Invoices to Pay",
        domain="[('partner_id', '=', partner_id), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']), ('id', '!=', current_invoice_id)]"
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Partner",
        related='visit_id.owner_id.partner_id',
        store=False
    )
    owner_unpaid_balance = fields.Float(
        string="Total Unpaid Balance",
        compute="_compute_owner_unpaid_balance",
        store=False,
        digits=(16, 2),
    )
    other_unpaid_count = fields.Integer(
        string="Other Unpaid Invoices",
        compute="_compute_other_unpaid_count",
        store=False
    )

    @api.depends('visit_id', 'visit_id.invoice_ids')
    def _compute_current_invoice(self):
        for wizard in self:
            if wizard.visit_id and wizard.visit_id.invoice_ids:
                current = wizard.visit_id.invoice_ids.filtered(
                    lambda inv: inv.payment_state in ['not_paid', 'partial']
                ).sorted('id', reverse=True)[:1]
                
                wizard.current_invoice_id = current
                wizard.current_invoice_amount = current.amount_residual if current else 0.0
            else:
                wizard.current_invoice_id = False
                wizard.current_invoice_amount = 0.0

    @api.depends('visit_id', 'partner_id', 'current_invoice_id')
    def _compute_other_unpaid_count(self):
        for wizard in self:
            if wizard.partner_id and wizard.current_invoice_id:
                count = self.env['account.move'].search_count([
                    ('partner_id', '=', wizard.partner_id.id),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('payment_state', 'in', ['not_paid', 'partial']),
                    ('id', '!=', wizard.current_invoice_id.id)
                ])
                wizard.other_unpaid_count = count
            else:
                wizard.other_unpaid_count = 0

    @api.depends('visit_id')
    def _compute_owner_unpaid_balance(self):
        for wizard in self:
            if wizard.visit_id:
                wizard.owner_unpaid_balance = wizard.visit_id.owner_unpaid_balance
            else:
                wizard.owner_unpaid_balance = 0.0

    @api.model
    def default_get(self, fields_list):
        res = super(VetAnimalVisitPaymentWizard, self).default_get(fields_list)
        
        if 'visit_id' in res and res['visit_id']:
            visit = self.env['vet.animal.visit'].browse(res['visit_id'])
            
            # Get current invoice
            current_invoice = visit.invoice_ids.filtered(
                lambda inv: inv.payment_state in ['not_paid', 'partial']
            ).sorted('id', reverse=True)[:1]
            
            # ALWAYS default to current invoice amount for 'current' mode
            if current_invoice:
                res['amount'] = current_invoice.amount_residual
                _logger.info("Payment Wizard: Set default amount to current invoice: %.2f", 
                           current_invoice.amount_residual)
            else:
                res['amount'] = 0.0
            
            # Set default journal
            if visit.company_id:
                default_journal = self.env['account.journal'].search([
                    ('company_id', '=', visit.company_id.id),
                    ('type', '=', 'cash')
                ], limit=1)
                
                if not default_journal:
                    default_journal = self.env['account.journal'].search([
                        ('company_id', '=', visit.company_id.id),
                        ('type', '=', 'bank')
                    ], limit=1)
                
                if default_journal:
                    res['journal_id'] = default_journal.id
        
        return res

    @api.onchange('payment_mode')
    def _onchange_payment_mode(self):
        """Update amount based on payment mode - but ONLY when mode actually changes"""
        # Don't process if we're in the middle of confirming payment
        if self.env.context.get('confirming_payment'):
            return
        
        _logger.info("Payment Wizard: _onchange_payment_mode triggered. Mode=%s, Current Amount=%.2f", 
                    self.payment_mode, self.amount)
        
        if self.payment_mode == 'current':
            if self.current_invoice_id:
                new_amount = self.current_invoice_amount
                _logger.info("Payment Wizard: Setting amount to current invoice: %.2f", new_amount)
                self.amount = new_amount
        elif self.payment_mode == 'all':
            new_amount = self.owner_unpaid_balance
            _logger.info("Payment Wizard: Setting amount to all unpaid: %.2f", new_amount)
            self.amount = new_amount
        elif self.payment_mode == 'other':
            if self.other_invoice_ids:
                new_amount = sum(self.other_invoice_ids.mapped('amount_residual'))
                _logger.info("Payment Wizard: Setting amount to selected invoices: %.2f", new_amount)
                self.amount = new_amount
            else:
                _logger.info("Payment Wizard: No other invoices selected, keeping current amount")

    @api.onchange('other_invoice_ids')
    def _onchange_other_invoice_ids(self):
        """Update amount when other invoices are selected"""
        if self.payment_mode == 'other' and self.other_invoice_ids:
            self.amount = sum(self.other_invoice_ids.mapped('amount_residual'))
            _logger.info("Payment Wizard: Updated amount from other_invoice_ids: %.2f", self.amount)

    def action_confirm_payment(self):
        self.ensure_one()
        
        # Create a new context to prevent onchange from firing during confirmation
        self = self.with_context(confirming_payment=True)
        
        _logger.info("=" * 80)
        _logger.info("PAYMENT WIZARD: Confirming payment")
        _logger.info("  Mode: %s", self.payment_mode)
        _logger.info("  Amount entered: %.2f", self.amount)
        _logger.info("  Current invoice amount: %.2f", self.current_invoice_amount)
        _logger.info("  Owner unpaid balance: %.2f", self.owner_unpaid_balance)
        _logger.info("=" * 80)
        
        visit = self.env['vet.animal.visit'].browse(self.visit_id.id)
        if not visit.exists():
            raise UserError(_("The visit record does not exist or has been deleted."))
        
        if self.journal_id.company_id != visit.company_id:
            raise UserError(
                _("Selected journal '%s' does not belong to visit branch '%s'. "
                  "Please select a journal from the correct branch.") 
                % (self.journal_id.name, visit.company_id.name)
            )
        
        partner = visit.owner_id.partner_id
        if not partner:
            raise UserError(_("Visit owner has no linked partner. Cannot process payment."))
        if not partner.property_account_receivable_id:
            raise UserError(_("Partner %s has no receivable account configured.") % partner.name)
        if not self.journal_id or not self.journal_id.default_account_id:
            raise UserError(_("Selected journal has no default account configured."))

        amount = self.amount
        if amount <= 0:
            raise UserError(_("Payment amount must be greater than zero."))

        # Determine which invoices to pay based on payment mode
        if self.payment_mode == 'current':
            if not self.current_invoice_id:
                raise UserError(_("No current invoice found for this visit."))
            invoices = self.current_invoice_id
            _logger.info("Payment mode 'current': Selected invoice %s with balance %.2f", 
                        invoices.name, invoices.amount_residual)
        elif self.payment_mode == 'other':
            if not self.other_invoice_ids:
                raise UserError(_("Please select at least one invoice to pay."))
            invoices = self.other_invoice_ids.sorted(lambda inv: (inv.invoice_date, inv.id))
            _logger.info("Payment mode 'other': Selected %d invoices", len(invoices))
        else:  # 'all'
            invoices = self.env['account.move'].search([
                ('partner_id', '=', partner.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial']),
            ], order='invoice_date asc, id asc')
            _logger.info("Payment mode 'all': Found %d unpaid invoices", len(invoices))

        if not invoices:
            raise UserError(_("No invoices found to pay."))

        # Validate amount against SELECTED invoices only
        total_residual = sum(invoices.mapped('amount_residual'))
        _logger.info("Total residual of selected invoices: %.2f", total_residual)
        
        if amount > total_residual:
            raise UserError(
                _("You are trying to pay %.2f but the selected invoices' total balance is only %.2f.") 
                % (amount, total_residual)
            )

        visit.with_context(from_payment_wizard=True).write({
            'latest_payment_amount': amount,
            'journal_id': self.journal_id.id
        })

        payments = self.env['account.payment']
        remaining_amount = amount

        try:
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                payment_amount = min(remaining_amount, invoice.amount_residual)
                if payment_amount <= 0:
                    continue

                PaymentRegister = self.env['account.payment.register']
                ctx = {
                    'active_model': 'account.move',
                    'active_ids': [invoice.id],
                    'default_amount': payment_amount,
                    'default_partner_id': partner.id,
                    'default_payment_type': 'inbound',
                    'default_partner_type': 'customer',
                    'default_journal_id': self.journal_id.id,
                    'force_journal_id': self.journal_id.id,
                    'default_payment_reference': f"Payment for {visit.name} - Invoice {invoice.name}",
                    'default_payment_difference_handling': 'open',
                    'skip_account_move_synchronization': True,
                }

                payment_wizard = PaymentRegister.with_context(ctx).create({})
                payment_wizard.payment_difference_handling = 'open'
                payment_result = payment_wizard.action_create_payments()

                new_payment = payment_result
                if isinstance(payment_result, dict) and 'res_id' in payment_result:
                    new_payment = self.env['account.payment'].browse(payment_result['res_id'])
                payments |= new_payment
                remaining_amount -= payment_amount
                _logger.info("Payment of %.2f registered for invoice %s", payment_amount, invoice.name)

        except Exception as e:
            _logger.warning("Standard payment register failed: %s. Using manual fallback.", str(e))
            remaining_amount = amount
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                payment_amount = min(remaining_amount, invoice.amount_residual)
                if payment_amount <= 0:
                    continue

                payment_move = self.env["account.move"].create({
                    'move_type': 'entry',
                    'date': fields.Date.context_today(self),
                    'ref': f"Payment for {visit.name} - Invoice {invoice.name}",
                    'journal_id': self.journal_id.id,
                    'line_ids': [
                        (0, 0, {
                            'name': f"Payment for {visit.name} - Invoice {invoice.name}",
                            'debit': 0.0,
                            'credit': payment_amount,
                            'account_id': partner.property_account_receivable_id.id,
                            'partner_id': partner.id,
                        }),
                        (0, 0, {
                            'name': f"Cash/Bank for {visit.name} - Invoice {invoice.name}",
                            'debit': payment_amount,
                            'credit': 0.0,
                            'account_id': self.journal_id.default_account_id.id,
                            'partner_id': partner.id,
                        }),
                    ],
                })
                payment_move.action_post()

                receivable_line = invoice.line_ids.filtered(
                    lambda l: l.account_id == partner.property_account_receivable_id and not l.reconciled
                )
                payment_line = payment_move.line_ids.filtered(
                    lambda l: l.account_id == partner.property_account_receivable_id
                )
                if receivable_line and payment_line:
                    try:
                        (receivable_line + payment_line).reconcile()
                    except Exception as recon_err:
                        _logger.error("Fallback reconciliation failed: %s", recon_err)

                remaining_amount -= payment_amount

        invoices._compute_payment_state()
        invoices.invalidate_recordset(['payment_state', 'amount_residual'])
        visit.invalidate_recordset(['payment_state', 'is_fully_paid', 'amount_received'])
        visit.with_context(skip_visit_validation=True)._sync_state_with_payment()

        _logger.info("Payment complete. Visit %s: Mode=%s, State=%s, payment_state=%s",
                    visit.name, self.payment_mode, visit.state, visit.payment_state)

        return self._generate_receipt(visit, invoices, payments[0] if payments else None)

    def _generate_receipt(self, visit, invoices, payment=None):
        """Generate custom receipt"""
        try:
            if not visit.contact_number:
                visit.contact_number = visit.owner_id.contact_number or ''
            return self.env.ref('vet_test.action_report_visit_receipt').report_action(visit)
        except Exception as e:
            _logger.error("Receipt generation failed: %s", e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Receipt Ready!'),
                    'message': _('Payment processed! Receipt printed.'),
                    'sticky': False,
                }
            }

class ReportVisitReceipt(models.AbstractModel):
    _name = 'report.vet_test.report_visit_receipt'
    _description = 'Visit Receipt Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['vet.animal.visit'].browse(docids)
        for doc in docs:
            _logger.info(
                    "Generating receipt for visit %s: subtotal=%s, total_amount=%s",
                    doc.name, doc.subtotal, doc.total_amount)
        return {
                'doc_ids': docs.ids,
                'doc_model': 'vet.animal.visit',
                'docs': docs,
                }
