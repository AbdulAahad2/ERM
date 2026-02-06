import logging
import re

from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def _validate_email(email):
    if not email:
        return True
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email.strip()) is not None


class VetAnimalOwner(models.Model):
    _name = 'vet.animal.owner'
    _description = 'Animal Owner'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    partner_id = fields.Many2one('res.partner', string="Contact", required=True, ondelete="cascade", index=True)
    notes = fields.Text("Additional Notes")
    active = fields.Boolean("Active", default=True, index=True)

    name = fields.Char(related="partner_id.name", store=True, readonly=False, tracking=True, index=True)
    contact_number = fields.Char(
            related="partner_id.mobile", 
            store=True, 
            readonly=False, 
            tracking=True, 
            index=True,
            search=lambda self, operator, value: [('partner_id.mobile', operator, value)]
            )
    email = fields.Char(related="partner_id.email", store=True, readonly=False, tracking=True)
    address = fields.Char(compute="_compute_address", string="Address", store=True, readonly=False, tracking=True)
    animal_ids = fields.One2many('vet.animal', 'owner_id', string="Animals")

    @api.depends('partner_id.street', 'partner_id.street2', 'partner_id.city', 'partner_id.zip', 
                 'partner_id.state_id', 'partner_id.country_id')
    def _compute_address(self):
        for record in self:
            record.address = record.partner_id._display_address(without_company=True) if record.partner_id else False

    @api.constrains('contact_number')
    def _check_owner_contact_number(self):
        if self.env.context.get('skip_owner_validation'):
            return

        # Batch validate all records at once
        records_to_check = []
        for record in self:
            if not record.partner_id:
                continue
            phone = record.contact_number
            if not phone:
                raise ValidationError(_("Contact number must be set for animal owners."))

            cleaned_phone = re.sub(r'\D', '', phone)
            if not re.fullmatch(r"\d{11}", cleaned_phone):
                raise ValidationError(_("Phone number must be exactly 11 digits."))

            records_to_check.append((record.id, cleaned_phone))

        if records_to_check:
            record_ids = [r[0] for r in records_to_check]
            phones = [r[1] for r in records_to_check]

            self.env.cr.execute("""
                SELECT contact_number, COUNT(*) 
                FROM vet_animal_owner 
                WHERE contact_number IN %s 
                    AND id NOT IN %s
                GROUP BY contact_number
                HAVING COUNT(*) > 0
                """, (tuple(phones), tuple(record_ids)))
            duplicates = self.env.cr.fetchall()
            if duplicates:
                raise ValidationError(_("Contact number must be unique among animal owners."))

    @api.constrains('email')
    def _check_email(self):
        for record in self:
            if record.email and not _validate_email(record.email):
                raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('partner_id'):
                partner_vals = {
                        'name': vals.get('name', 'Unknown Owner'),
                        'mobile': vals.get('contact_number'),
                        'email': vals.get('email'),
                        'is_vet_owner': True,
                        }

                if partner_vals.get('email') and not _validate_email(partner_vals['email']):
                    raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

                if not partner_vals.get('mobile'):
                    raise ValidationError(_("Contact number must be set for animal owners."))

                cleaned_phone = re.sub(r'\D', '', partner_vals['mobile'])
                if not re.fullmatch(r"\d{11}", cleaned_phone):
                    raise ValidationError(_("Phone number must be exactly 11 digits."))

                self.env.cr.execute("""
                    SELECT id FROM vet_animal_owner 
                    WHERE contact_number = %s 
                    LIMIT 1
                """, (cleaned_phone,))

                if self.env.cr.fetchone():
                    raise ValidationError(_("Contact number must be unique among animal owners."))

                partner = self.env['res.partner'].with_context(skip_owner_create=True).create(partner_vals)
                vals['partner_id'] = partner.id
            else:
                if not self.env.context.get('skip_partner_write'):
                    partner = self.env['res.partner'].browse(vals['partner_id'])
                    if not partner.is_vet_owner:
                        partner.with_context(skip_owner_create=True).write({'is_vet_owner': True})

        return super().create(vals_list)

    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_vet_owner_contact 
            ON vet_animal_owner(contact_number);
        """)

        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_vet_owner_partner 
            ON vet_animal_owner(partner_id);
        """)


class ResPartnerInherit(models.Model):
    _inherit = "res.partner"
    owner_id = fields.One2many("vet.animal.owner", "partner_id", string="Vet Owner")
    animal_ids = fields.One2many("vet.animal", "partner_id", string="Animals")
    dob = fields.Date(string="Date of Birth", tracking=True)
    age = fields.Char(string="Age", compute="_compute_age", store=True)
    is_vet_owner = fields.Boolean(
            string="Is Vet Animal Owner", 
            default=False, 
            help="Indicates if this partner is an animal owner in the vet system",
            index=True
            )

    @api.depends('dob')
    def _compute_age(self):
        for record in self:
            if record.dob:
                delta = relativedelta(fields.Date.today(), record.dob)
                years, months = delta.years, delta.months
                if years > 0:
                    record.age = f"{years} year{'s' if years > 1 else ''} {months} month{'s' if months > 1 else ''}" if months else f"{years} year{'s' if years > 1 else ''}"
                else:
                    record.age = f"{months} month{'s' if months > 1 else ''}"
            else:
                record.age = "0"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_vet_owner') and not vals.get('user_ids'):
                if vals.get('email') and not _validate_email(vals['email']):
                    raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

                phone = vals.get('mobile', '')
                if not phone:
                    raise ValidationError(_("Contact number must be set for animal owners."))

                cleaned_phone = re.sub(r'\D', '', phone)
                if not re.fullmatch(r"\d{11}", cleaned_phone):
                    raise ValidationError(_("Phone number must be exactly 11 digits."))

                self.env.cr.execute("""
                    SELECT id FROM vet_animal_owner 
                    WHERE contact_number = %s 
                    LIMIT 1
                """, (cleaned_phone,))

                if self.env.cr.fetchone():
                    raise ValidationError(_("Contact number must be unique among animal owners."))

        partners = super().create(vals_list)

        for partner in partners:
            if self.env.context.get("skip_owner_create"):
                continue
            if partner.is_vet_owner and not partner.owner_id and not partner.user_ids:
                self.env['vet.animal.owner'].with_context(
                        skip_owner_validation=True, 
                        skip_partner_write=True
                        ).create({"partner_id": partner.id})

        return partners

    def write(self, vals): 
        creating_new_owners = vals.get('is_vet_owner') == True

        # Only validate if we're updating mobile/email AND not creating new owners
        if ('mobile' in vals or 'email' in vals) and not creating_new_owners:
            for partner in self:
                if partner.is_vet_owner and not partner.user_ids:
                    email = vals.get('email', partner.email)
                    if email and not _validate_email(email):
                        raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

                    mobile = vals.get('mobile', partner.mobile)
                    if not mobile:
                        raise ValidationError(_("Contact number must be set for animal owners."))

                    cleaned_phone = re.sub(r'\D', '', mobile) if mobile else ''
                    if not cleaned_phone:
                        raise ValidationError(_("Contact number must be set for animal owners."))
                    if not re.fullmatch(r"\d{11}", cleaned_phone):
                        raise ValidationError(_("Phone number must be exactly 11 digits."))

                    self.env.cr.execute("""
                        SELECT id FROM vet_animal_owner 
                        WHERE contact_number = %s AND partner_id != %s 
                        LIMIT 1
                    """, (cleaned_phone, partner.id))

                    if self.env.cr.fetchone():
                        raise ValidationError(_("Contact number must be unique among animal owners."))

        if creating_new_owners:
            res = super(ResPartnerInherit, self.with_context(skip_vet_owner_constraint=True)).write(vals)
        else:
            res = super().write(vals)

        if creating_new_owners:
            for partner in self:
                if self.env.context.get("skip_owner_create"):
                    continue
                if partner.user_ids:
                    continue
                if partner.owner_id:
                    continue
                if not partner.mobile:
                    continue

                cleaned_phone = re.sub(r'\D', '', partner.mobile)
                if not re.fullmatch(r"\d{11}", cleaned_phone):
                    continue

                try:
                    owner = self.env['vet.animal.owner'].with_context(
                            skip_partner_create=True, 
                            skip_owner_validation=True, 
                            skip_partner_write=True
                            ).create({
                                "partner_id": partner.id,
                                })
                    _logger.info(f"Successfully created vet owner {owner.id} for partner {partner.id}")
                except Exception as e:
                    _logger.error(f"Failed to create vet owner for partner {partner.id}: {str(e)}")
                    continue

        return res

    @api.constrains('mobile', 'email')
    def _check_mobile_and_email(self):
        if self.env.context.get('skip_vet_owner_constraint'):
            return

        for record in self:
            if not record.is_vet_owner or record.user_ids:
                continue

            if self.env.context.get('skip_owner_validation'):
                continue

            if not record.owner_id:
                continue

            if record.email and not _validate_email(record.email):
                raise ValidationError(_("Please enter a valid email address (e.g., example@domain.com)."))

            mobile = record.mobile
            if not mobile:
                raise ValidationError(_("Contact number must be set for animal owners."))

            cleaned_phone = re.sub(r'\D', '', mobile)
            if not re.fullmatch(r"\d{11}", cleaned_phone):
                raise ValidationError(_("Phone number must be exactly 11 digits."))

            self.env.cr.execute("""
                SELECT p.id 
                FROM res_partner p
                LEFT JOIN res_users u ON u.partner_id = p.id
                WHERE p.mobile ILIKE %s 
                    AND p.id != %s 
                    AND u.id IS NULL
                LIMIT 1
            """, (f'%{cleaned_phone}%', record.id))

            if self.env.cr.fetchone():
                raise ValidationError(_("Contact number must be unique among customers."))
