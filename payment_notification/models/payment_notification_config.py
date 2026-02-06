from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)
class PaymentNotificationConfig(models.Model):
    _name = 'payment.notification.config'
    _description = 'Payment Notification Configuration'
    _rec_name = 'notification_value'

    notification_value = fields.Integer(
        string='Notification Time',
        required=True,
        default=2,
        help='Time value before due date to send notification'
    )

    notification_unit = fields.Selection([
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
    ], string='Time Unit', default='days', required=True)

    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    cron_interval = fields.Integer(
        string='Check Frequency (Minutes)',
        default=60,
        help='How often the system checks for payments (in minutes). Lower values for testing.'
    )

    @api.model
    def get_config(self):
        """Get the active configuration"""
        config = self.search([
            ('company_id', '=', self.env.company.id),
            ('active', '=', True)
        ], limit=1)

        if not config:
            # Create default config
            config = self.create({
                'notification_value': 2,
                'notification_unit': 'days',
                'cron_interval': 60,
            })

        return config

    def write(self, vals):
        """Update cron job when configuration changes"""
        res = super(PaymentNotificationConfig, self).write(vals)
        if 'cron_interval' in vals:
            self._update_cron_interval()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Update cron job when configuration is created"""
        configs = super(PaymentNotificationConfig, self).create(vals_list)
        configs._update_cron_interval()
        return configs

    def _update_cron_interval(self):
        """Update the cron job interval"""
        cron = self.env.ref('payment_due_notifications.ir_cron_check_payment_due',
                            raise_if_not_found=False)
        if cron and self.cron_interval:
            cron.write({
                'interval_number': self.cron_interval,
                'interval_type': 'minutes'
            })
            _logger.info(f'Cron interval updated to {self.cron_interval} minutes')

    def action_run_cron_now(self):
        """Manually trigger the cron job"""
        self.ensure_one()
        try:
            self.env['account.move']._cron_check_payment_due_dates()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Manual Check Complete',
                    'message': 'Payment notification check has been executed. Check the logs for details.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Failed to run check: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }