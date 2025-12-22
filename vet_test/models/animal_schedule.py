from odoo import models, fields, api

class VetAnimalSchedule(models.Model):
    _name = 'vet.animal.schedule'
    _description = 'Animal Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string="Appointment Reference", required=True, default="New", tracking=True)
    animal_id = fields.Many2one('vet.animal', string='Animal', required=True, tracking=True)
    owner_id = fields.Many2one('vet.animal.owner', string="Owner", related='animal_id.owner_id', store=True, readonly=True)
    doctor_id = fields.Many2one('vet.animal.doctor', string='Doctor', required=True, tracking=True)
    appointment_date = fields.Date(string='Appointment Date', required=True, tracking=True)
    reason = fields.Text(string="Reason for Appointment", tracking=True)
    notes = fields.Text(string="Additional Notes", tracking=True)  # Merged duplicate field
    status = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    active = fields.Boolean(string='Active', default=True)  # For archiving

    _sql_constraints = [
        ('unique_appointment', 'unique(animal_id, doctor_id, appointment_date)', 'This appointment already exists!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Batch-safe creation with sequence for name and fallback for appointment_date."""
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('vet.animal.schedule') or 'SCH00000'
            if not vals.get('appointment_date'):
                vals['appointment_date'] = fields.Date.today()
        return super(VetAnimalSchedule, self).create(vals_list)

    # Actions
    def action_confirm(self):
        self.status = 'confirmed'

    def action_done(self):
        self.status = 'completed'

    def action_cancel(self):
        self.status = 'cancelled'

    def action_reset_draft(self):
        self.status = 'draft'
