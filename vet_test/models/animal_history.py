import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
class VetAnimalHistoryService(models.TransientModel):
    _name = "vet.animal.history.service"
    _description = "Animal Visit History Service"
    _inherit = ['ir.autovacuum']
    _transient_max_hours = 24

    history_line_id = fields.Many2one("vet.animal.history.line", string="History Line", ondelete="cascade")
    name = fields.Char(string="Service/Treatment")
    amount = fields.Float(string="Amount")
class VetAnimalHistoryLine(models.TransientModel):
    _name = "vet.animal.history.line"
    _description = "Animal Visit History Line"
    _inherit = ['ir.autovacuum']
    _transient_max_hours = 24

    wizard_id = fields.Many2one("vet.animal.history.wizard", string="Wizard", ondelete="cascade")
    visit_id = fields.Many2one("vet.animal.visit", string="Visit")
    visit_date = fields.Datetime(string="Visit Date")
    doctor = fields.Char(string="Doctor")
    notes = fields.Text(string="Notes")
    total_amount = fields.Float(string="Total Amount")
    service_line_ids = fields.One2many("vet.animal.history.service", "history_line_id", string="Services/Treatments")
    service_names = fields.Char(string="Services/Treatments", compute="_compute_service_names", store=False)

    @api.depends('service_line_ids')
    def _compute_service_names(self):
        for line in self:
            services = [f"{s.name} (Rs.{s.amount:.2f})" for s in line.service_line_ids]
            line.service_names = ", ".join(services) or "N/A"

class VetAnimalHistoryWizard(models.TransientModel):
    _name = "vet.animal.history.wizard"
    _description = "Animal Visit History Search"

    # ─────────────────────────────────────────────
    # 🔹 Owner Info Section
    # ─────────────────────────────────────────────
    owner_id = fields.Many2one("vet.animal.owner", string="Owner")
    contact_number = fields.Char(string="Owner Contact")
    animal_ids = fields.Many2many("vet.animal", string="Owner's Animals", compute="_compute_animal_ids", store=False)
    selected_animal_id = fields.Many2one("vet.animal", string="Select Animal")
    owner_unpaid_balance = fields.Float(string="Unpaid Balance", compute="_compute_unpaid_balance", store=False)

    # ─────────────────────────────────────────────
    # 🔹 Animal Search Section
    # ─────────────────────────────────────────────
    animal_id = fields.Many2one("vet.animal", string="Animal")
    animal_name = fields.Char(string="Animal Name", readonly=False)
    history_line_ids = fields.One2many("vet.animal.history.line", "wizard_id", string="History Lines")
    service_name = fields.Char(string="Service/Treatment", compute="_compute_service_name", store=False)
    total_visits = fields.Integer(string="Total Visits", readonly=True)

    # ─────────────────────────────────────────────
    # 🔹 Computed Fields
    # ─────────────────────────────────────────────
    def _compute_service_name(self):
        for rec in self:
            rec.service_name = False

    @api.depends("owner_id")
    def _compute_animal_ids(self):
        for rec in self:
            if rec.owner_id:
                rec.animal_ids = self.env["vet.animal"].search([("owner_id", "=", rec.owner_id.id)])
            else:
                rec.animal_ids = False

    @api.depends("owner_id")
    def _compute_unpaid_balance(self):
        """Compute owner's unpaid invoices (open state). Only include posted invoices."""
        for rec in self:
            if rec.owner_id:
                invoices = self.env["account.move"].search([
                    ("partner_id", "=", rec.owner_id.partner_id.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),  # ← Only posted (valid) invoices
                    ("payment_state", "in", ["not_paid", "partial"])
                ])
                rec.owner_unpaid_balance = sum(invoices.mapped("amount_residual"))
            else:
                rec.owner_unpaid_balance = 0.0

    # ─────────────────────────────────────────────
    # 🔹 Onchange Handlers
    # ─────────────────────────────────────────────
    @api.onchange("owner_id")
    def _onchange_owner(self):
        """Update contact and animal list when owner changes. Auto-select animal if only one."""
        # ✅ Clear previous animal selections first
        self.selected_animal_id = False
        self.animal_id = False
        self.animal_name = False
        self.history_line_ids = [(5, 0, 0)]  # Clear history lines
        self.total_visits = 0
        
        if self.owner_id:
            self.contact_number = self.owner_id.contact_number
            animals = self.env["vet.animal"].search([("owner_id", "=", self.owner_id.id)])
            self.animal_ids = animals
            
            if len(animals) == 1:
                self.selected_animal_id = animals[0]
                self.animal_id = animals[0]
                self.animal_name = animals[0].name
        else:
            self.contact_number = False
            self.animal_ids = False

    @api.onchange('contact_number')
    def _onchange_contact_number(self):
        # ✅ Clear all animal-related fields first
        self.owner_id = False
        self.animal_id = False
        self.selected_animal_id = False
        self.animal_name = False
        self.history_line_ids = [(5, 0, 0)]  # Clear history lines
        self.total_visits = 0

        if self.contact_number:
            owner = self.env['vet.animal.owner'].search([
                ('contact_number', '=', self.contact_number.strip())
            ], limit=1)

            if owner:
                self.owner_id = owner  # ✅ Assign the vet.animal.owner record

                animals = self.env['vet.animal'].search([('owner_id', '=', owner.id)])
                
                # ✅ Auto-select animal if owner has only one pet
                if len(animals) == 1:
                    self.animal_id = animals[0]
                    self.selected_animal_id = animals[0]
                    self.animal_name = animals[0].name

                domain = {'animal_id': [('owner_id', '=', owner.id)]}
            else:
                domain = {'animal_id': [('id', '!=', False)]}
        else:
            domain = {'animal_id': [('id', '!=', False)]}

        return {
            'domain': domain,
            'value': {
                'owner_id': self.owner_id.id if self.owner_id else False,
                'animal_id': self.animal_id.id if self.animal_id else False
            }
        }

    @api.onchange("selected_animal_id")
    def _onchange_selected_animal(self):
        """Sync selected_animal_id with animal_id (for search logic)."""
        _logger.info("_onchange_selected_animal called with: %s", self.selected_animal_id)
        if self.selected_animal_id:
            self.animal_id = self.selected_animal_id
            self.animal_name = self.selected_animal_id.name
            # ✅ Clear previous history when changing animal
            self.history_line_ids = [(5, 0, 0)]
            self.total_visits = 0
            _logger.info("Set animal_id to %s and animal_name to %s", self.animal_id, self.animal_name)

    def action_search_history(self):
        self.ensure_one()
        _logger.info(
            "User %s running action_search_history with groups: %s",
            self.env.user.name, self.env.user.groups_id.mapped("name"),
        )

        # ✅ Use selected_animal_id if animal_id is empty (since onchange doesn't persist)
        animal_for_search = self.selected_animal_id or self.animal_id
        
        _logger.info("BEFORE SEARCH - animal_id: %s, selected_animal_id: %s, animal_name: %s", 
                     self.animal_id, self.selected_animal_id, self.animal_name)

        domain = []

        # ✅ Prioritize selected_animal_id over other search methods
        if animal_for_search:
            domain.append(("animal_id", "=", animal_for_search.id))
            _logger.info("Searching by animal: %s (id: %s)", animal_for_search.name, animal_for_search.id)
        elif self.animal_name:
            animals = self.env["vet.animal"].search([("name", "ilike", self.animal_name)])
            _logger.info("Searching by animal_name '%s', found animals: %s", self.animal_name, animals.ids)
            domain.append(("animal_id", "in", animals.ids)) if animals else domain.append(("id", "=", 0))
        elif self.contact_number:
            owner = self.env["vet.animal.owner"].search([("contact_number", "=", self.contact_number)], limit=1)
            if owner:
                animals = self.env["vet.animal"].search([("owner_id", "=", owner.id)])
                _logger.info("Searching by contact '%s', owner: %s, animals: %s", 
                            self.contact_number, owner.id, animals.ids)
                domain.append(("animal_id", "in", animals.ids)) if animals else domain.append(("id", "=", 0))
            else:
                _logger.warning("No owner found for contact: %s", self.contact_number)
                domain.append(("id", "=", 0))
        else:
            _logger.warning("No search criteria provided")
            domain.append(("id", "=", 0))

        visits = self.env["vet.animal.visit"].search(domain, order="date desc")
        _logger.info("Found %s visits for domain %s", len(visits), domain)
        
        if visits:
            _logger.info("First 3 visits: %s", [(v.id, v.name, v.animal_id.name if v.animal_id else 'No Animal') for v in visits[:3]])

        lines = []
        for visit in visits:
            service_lines = []

            if visit.treatment_charge > 0:
                service_lines.append((0, 0, {
                    "name": "Treatment Charge",
                    "amount": visit.treatment_charge,
                }))

            for s in visit.service_line_ids.sudo():
                service_name = s.service_id.name or s.product_id.name or "Service Charge"
                service_lines.append((0, 0, {
                    "name": service_name,
                    "amount": s.subtotal,
                }))
                if s.service_id and s.service_id.product_id:
                    for product in s.service_id.product_id:
                        service_lines.append((0, 0, {
                            "name": f"{product.name} (via {s.service_id.name})",
                            "amount": product.lst_price or 0.0,
                        }))

            for test in visit.test_line_ids.sudo():
                test_name = test.service_id.name or test.product_id.name or "Unnamed Test"
                service_lines.append((0, 0, {
                    "name": test_name,
                    "amount": test.subtotal or 0.0,
                }))

            for vaccine in visit.medicine_line_ids.sudo():
                vaccine_name = vaccine.service_id.name or vaccine.product_id.name or "Unnamed Vaccine"
                service_lines.append((0, 0, {
                    "name": vaccine_name,
                    "amount": vaccine.subtotal or 0.0,
                }))

            _logger.info("Visit %s: Creating %s service lines", visit.name, len(service_lines))

            lines.append((0, 0, {
                "visit_id": visit.id,
                "visit_date": visit.date,
                "doctor": visit.doctor_id.name,
                "notes": visit.notes or "-",
                "total_amount": visit.total_amount,
                "service_line_ids": service_lines,
            }))

        # ✅ Build update values with the correct animal info
        update_vals = {
            'history_line_ids': [(5, 0, 0)] + lines,  # Clear old lines first
            'total_visits': len(visits),
        }
        
        # ✅ Preserve the animal that was used for search
        if animal_for_search:
            update_vals['animal_id'] = animal_for_search.id
            update_vals['animal_name'] = animal_for_search.name
            update_vals['selected_animal_id'] = animal_for_search.id
            
        if self.owner_id:
            update_vals['owner_id'] = self.owner_id.id
        if self.contact_number:
            update_vals['contact_number'] = self.contact_number
        if self.animal_ids:
            update_vals['animal_ids'] = [(6, 0, self.animal_ids.ids)]
        
        _logger.info("Updating wizard with values: %s", update_vals)
        self.write(update_vals)
        
        # ✅ Verify after write
        _logger.info("AFTER WRITE - animal_id: %s, animal_name: %s", self.animal_id, self.animal_name)
        
        _logger.info("Wizard %s updated with %s lines (total %s visits)", self.id, len(lines), self.total_visits)

        # ✅ Return reload
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vet.animal.history.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'views': [(False, 'form')],
            'target': 'new',
            'context': dict(self.env.context),
        }

    def _return_wizard_action(self):
        """Reopen wizard with updated results."""
        return {
            "type": "ir.actions.act_window",
            "res_model": "vet.animal.history.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
