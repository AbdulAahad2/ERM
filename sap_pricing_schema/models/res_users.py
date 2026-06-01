from odoo import _, fields, models
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    is_sap_pricing_user = fields.Boolean(
        string='Odoo Pricing User',
        compute='_compute_sap_pricing_roles',
    )
    is_sap_pricing_admin = fields.Boolean(
        string='Odoo Pricing Administrator',
        compute='_compute_sap_pricing_roles',
    )

    def _compute_sap_pricing_roles(self):
        user_group = self.env.ref('sap_pricing_schema.group_sap_pricing_user', raise_if_not_found=False)
        admin_group = self.env.ref('sap_pricing_schema.group_sap_pricing_admin', raise_if_not_found=False)
        for user in self:
            user.is_sap_pricing_user = bool(user_group and user_group in user.groups_id)
            user.is_sap_pricing_admin = bool(admin_group and admin_group in user.groups_id)

    def _check_can_manage_sap_pricing_roles(self):
        current_user = self.env.user
        if not (
            current_user.has_group('sap_pricing_schema.group_sap_pricing_admin')
            or current_user.has_group('base.group_system')
        ):
            raise AccessError(_('Only Odoo Pricing Administrators can manage Odoo Pricing access.'))

    def _set_sap_pricing_role(self, role):
        self._check_can_manage_sap_pricing_roles()
        user_group = self.env.ref('sap_pricing_schema.group_sap_pricing_user')
        admin_group = self.env.ref('sap_pricing_schema.group_sap_pricing_admin')

        commands = [(3, user_group.id), (3, admin_group.id)]
        if role == 'user':
            commands.append((4, user_group.id))
        elif role == 'admin':
            commands.append((4, admin_group.id))

        self.sudo().write({'groups_id': commands})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Odoo Pricing Access Updated'),
                'message': _('The selected user access was updated. Ask the user to refresh or sign in again.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_make_sap_pricing_user(self):
        return self._set_sap_pricing_role('user')

    def action_make_sap_pricing_admin(self):
        return self._set_sap_pricing_role('admin')

    def action_remove_sap_pricing_access(self):
        return self._set_sap_pricing_role(False)
