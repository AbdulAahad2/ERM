# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


def _normalize_phone(phone):
    return re.sub(r'\D', '', str(phone or ''))


def _validate_email(email):
    """Validate email format using regex"""
    if not email:
        return True  # Email is optional
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email.strip()) is not None


class VetAnimalDoctor(models.Model):
    _name = 'vet.animal.doctor'
    _description = 'Animal Doctor (Global Phone + Company Filter)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char("Doctor Name", required=True, tracking=True)

    company_id = fields.Many2one(
        'res.company',
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True
    )

    contact_number = fields.Char("Contact Number", required=True, tracking=True, index=True)
    email = fields.Char("Email", tracking=True)
    specialization = fields.Char("Specialization", tracking=True)
    appointments = fields.One2many('vet.animal.schedule', 'doctor_id', string="Appointments")
    visit_ids = fields.One2many('vet.animal.visit', 'doctor_id', string='Visits')
    notes = fields.Text("Notes")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_contact_global',
         'unique(contact_number)',
         'Contact number must be unique across all companies!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('contact_number'):
                vals['contact_number'] = _normalize_phone(vals['contact_number'])
        return super().create(vals_list)

    def write(self, vals):
        if 'contact_number' in vals and vals['contact_number']:
            vals['contact_number'] = _normalize_phone(vals['contact_number'])
        return super().write(vals)

    @api.constrains('contact_number')
    def _check_contact_number(self):
        for record in self:
            phone = _normalize_phone(record.contact_number)
            if len(phone) != 11:
                raise ValidationError(_("Contact number must be exactly 11 digits."))

            dup = self.sudo().search([
                ('id', '!=', record.id),
                ('contact_number', '!=', False)
            ])
            for d in dup:
                if _normalize_phone(d.contact_number) == phone:
                    raise ValidationError(
                        _("This contact number is already used by Dr. %s in company '%s'.") %
                        (d.name, d.company_id.name)
                    )

    @api.constrains('email')
    def _check_email(self):
        for record in self:
            if record.email and not _validate_email(record.email):
                raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

    @api.model
    def search(self, args, offset=0, limit=None, order=None):
        args = (args or []) + [('company_id', '=', self.env.company.id)]
        return super().search(args, offset=offset, limit=limit, order=order)
