from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VetService(models.Model):
    _name = "vet.service"
    _description = "Vet Service / Test / Vaccine"
    _order = "name"

    name = fields.Char("Name", required=True)
    service_type = fields.Selection([
        ('service', 'Service'),
        ('vaccine', 'Vaccine'),
        ('test', 'Test')
    ], string="Type", required=True, default='service')

    price = fields.Float("Price", required=True, default=0.0)

    product_id = fields.Many2one(
        "product.product",
        string="Linked Product",
        ondelete="set null"
    )

    description = fields.Text("Description")

    combo_choice_ids = fields.Many2many(
        'product.combo',
        'vet_service_combo_rel',
        'service_id',
        'combo_id',
        string="Test Combo Choices"
    )

    def _get_product_type(self, service_type):
        """Prevent combo product creation until combos exist."""
        if service_type == 'test':
            return 'service'  # TEMPORARY type, converted later
        return {
            'service': 'service',
            'vaccine': 'consu',
        }.get(service_type, 'service')

    def _get_product_tracking(self, service_type):
        return {
            'service': 'none',
            'vaccine': 'lot',
            'test': 'lot',
        }.get(service_type, 'none')

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:

            if vals.get('service_type') == 'test':
                combo_cmds = vals.get('combo_choice_ids', [])
                if not combo_cmds:
                    raise ValidationError(
                        "Test services must have at least one combo choice."
                    )

            vals.setdefault('price', 0.0)

            if vals.get('service_type') == 'test':
                continue

            if not vals.get('product_id'):
                pt = self._get_product_type(vals['service_type'])
                tracking = self._get_product_tracking(vals['service_type'])
                
                product_vals = {
                    'name': vals.get('name', 'New Service'),
                    'list_price': vals.get('price', 0.0),
                    'type': pt,
                    'tracking': tracking,
                    'taxes_id': [(5, 0, 0)],
                    'supplier_taxes_id': [(5, 0, 0)],
                }
                
                # Set is_storable based on service type
                if vals['service_type'] == 'vaccine':
                    product_vals['is_storable'] = True
                else:
                    product_vals['is_storable'] = False

                product = self.env['product.product'].create(product_vals)
                vals['product_id'] = product.id

        records = super().create(vals_list)

        for rec in records:
            if rec.service_type == 'test':
                rec._sync_combo_choices()

        for rec in records:
            service_type_label = dict(rec._fields['service_type'].selection).get(rec.service_type, 'Service')
            message = f'{service_type_label} "{rec.name}" has been created successfully.'
            rec._show_notification('Success!', message, 'success')

        return records


    def write(self, vals):
        res = super().write(vals)

        for rec in self:

            if rec.service_type == 'test' and not rec.combo_choice_ids:
                raise ValidationError(
                    "Test services must have at least one combo choice."
                )

            if rec.product_id:
                product_vals = {}

                if 'name' in vals:
                    product_vals['name'] = vals['name']

                if 'price' in vals:
                    product_vals['list_price'] = vals['price']

                if 'service_type' in vals:
                    if vals['service_type'] == 'vaccine':
                        product_vals['is_storable'] = True
                    elif vals['service_type'] != 'test':
                        product_vals['is_storable'] = False

                if 'service_type' in vals and vals['service_type'] != 'test':
                    product_vals['type'] = self._get_product_type(vals['service_type'])
                    product_vals['tracking'] = self._get_product_tracking(vals['service_type'])

                if product_vals:
                    rec.product_id.write(product_vals)

            if rec.service_type == 'test' and 'combo_choice_ids' in vals:
                rec._sync_combo_choices()

        return res

    def unlink(self):
        """Delete linked products when service is deleted."""
        products_to_delete = self.mapped('product_id').filtered(lambda p: p)
        
        res = super().unlink()
        
        if products_to_delete:
            products_to_delete.unlink()
        
        return res


    def _sync_combo_choices(self):
        """Create + sync combo product ONLY after combos exist."""
        self.ensure_one()

        if self.service_type != 'test':
            return

        if not self.product_id:
            product = self.env['product.product'].create({
                'name': self.name,
                'list_price': self.price,
                'type': 'service',   # Start as service, convert later
                'tracking': 'lot',
                'taxes_id': [(5, 0, 0)],
                'supplier_taxes_id': [(5, 0, 0)],
            })
            self.product_id = product.id

        tmpl = self.product_id.product_tmpl_id

        tmpl.write({
            'type': 'combo',
            'combo_ids': [(6, 0, self.combo_choice_ids.ids)],
        })

    def _show_notification(self, title, message, notification_type='info'):
        """Display a notification to the user."""
        self.ensure_one()
        return self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'title': title,
                'message': message,
                'type': notification_type,
                'sticky': False,
            }
        )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.price = self.product_id.list_price or 0.0
            if not self.name:
                self.name = self.product_id.name
