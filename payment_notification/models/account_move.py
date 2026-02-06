from odoo import models, fields, api
from datetime import timedelta, datetime
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    notification_sent = fields.Boolean(
        string='Payment Notification Sent',
        default=False,
        help='Indicates if the payment reminder has been sent'
    )

    last_notification_check = fields.Datetime(
        string='Last Notification Check',
        help='Last time this invoice was checked for notification'
    )

    def _cron_check_payment_due_dates(self):
        """
        Scheduled action to check for payments due based on configuration
        """
        _logger.info('=' * 80)
        _logger.info('PAYMENT NOTIFICATION CRON STARTED')
        _logger.info('=' * 80)

        try:
            config = self.env['payment.notification.config'].get_config()
            _logger.info(f'Config loaded: {config.notification_value} {config.notification_unit}')
        except Exception as e:
            _logger.error(f'Failed to load config: {str(e)}')
            return False

        now = datetime.now()
        _logger.info(f'Current time: {now}')

        # Calculate the notification threshold based on config
        if config.notification_unit == 'minutes':
            threshold = timedelta(minutes=config.notification_value)
        elif config.notification_unit == 'hours':
            threshold = timedelta(hours=config.notification_value)
        else:  # days
            threshold = timedelta(days=config.notification_value)

        notification_datetime = now + threshold

        _logger.info(f'Looking for payments due around: {notification_datetime}')
        _logger.info(f'Threshold: {config.notification_value} {config.notification_unit}')

        # Find all unpaid invoices/bills
        moves = self.search([
            ('move_type', 'in', ['out_invoice', 'in_invoice']),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('notification_sent', '=', False),
            ('invoice_date_due', '!=', False),
        ])

        _logger.info(f'Found {len(moves)} unpaid invoices/bills to check')

        notified_count = 0

        for move in moves:
            # Convert due date to datetime for comparison
            # Important: invoice_date_due is a DATE field, we need to consider it as end of day
            due_date = move.invoice_date_due

            # For minute/hour testing, we need to be more flexible
            # Calculate days until due
            days_until_due = (due_date - now.date()).days

            _logger.info(f'Checking {move.name}: Due date {due_date}, Days until due: {days_until_due}')

            # Check if we should notify based on the configured threshold
            should_notify = False

            if config.notification_unit == 'minutes':
                # For minutes: if due date is today or tomorrow, we should notify
                # This is because invoice_date_due is just a DATE, not DATETIME
                total_minutes = config.notification_value
                days_threshold = 0 if total_minutes < 1440 else total_minutes // 1440  # 1440 min = 1 day

                should_notify = (days_until_due <= days_threshold)
                _logger.info(
                    f'  Minutes check: due in {days_until_due} days, threshold {days_threshold} days, notify: {should_notify}')

            elif config.notification_unit == 'hours':
                # For hours: similar logic
                total_hours = config.notification_value
                days_threshold = 0 if total_hours < 24 else total_hours // 24

                should_notify = (days_until_due <= days_threshold)
                _logger.info(
                    f'  Hours check: due in {days_until_due} days, threshold {days_threshold} days, notify: {should_notify}')

            else:  # days
                # For days, check if due date matches the notification date
                notification_date = (now + threshold).date()
                should_notify = (due_date == notification_date)
                _logger.info(
                    f'  Days check: {should_notify} (notification date: {notification_date}, due date: {due_date})')

            if should_notify:
                _logger.info(f'  ✓ SENDING NOTIFICATION for {move.name}')
                try:
                    move._send_payment_due_notification(config)
                    move.notification_sent = True
                    move.last_notification_check = now
                    notified_count += 1
                except Exception as e:
                    _logger.error(f'  ✗ Failed to send notification for {move.name}: {str(e)}')
            else:
                _logger.info(f'  ✗ Not in notification window')

        _logger.info(f'CRON COMPLETED: Sent {notified_count} payment notifications')
        _logger.info('=' * 80)

        return True

    def _send_payment_due_notification(self, config=None):
        """Send notification for payment due"""
        self.ensure_one()

        if not config:
            config = self.env['payment.notification.config'].get_config()

        # Determine the document type
        doc_type = 'Customer Invoice' if self.move_type == 'out_invoice' else 'Vendor Bill'

        # Get users to notify based on document type
        users_to_notify = self._get_users_to_notify()

        if not users_to_notify:
            _logger.warning(f'No users found to notify for {self.name}')
            return

        # Calculate time until due
        time_desc = self._get_time_until_due_description(config)

        # Send inbox notification to each user
        for user in users_to_notify:
            self._send_inbox_notification(user, doc_type, time_desc)

        # Create activity for tracking
        self._create_payment_activity(users_to_notify[0], time_desc)

        # Send email notification (optional)
        self._send_payment_due_email(time_desc)

        _logger.info(f'Payment notification sent for {self.name} to {len(users_to_notify)} users')

    def _get_time_until_due_description(self, config):
        """Get human-readable description of time until due"""
        now = datetime.now()
        due_date = self.invoice_date_due
        days_diff = (due_date - now.date()).days

        if config.notification_unit == 'minutes':
            if days_diff == 0:
                return "today"
            elif days_diff == 1:
                return "tomorrow"
            else:
                return f"in {days_diff} days"
        elif config.notification_unit == 'hours':
            if days_diff == 0:
                return "today"
            elif days_diff == 1:
                return "tomorrow"
            else:
                return f"in {days_diff} days"
        else:  # days
            if days_diff == 0:
                return "today"
            elif days_diff == 1:
                return "tomorrow"
            elif days_diff == 2:
                return "in 2 days"
            else:
                return f"in {days_diff} days"

    def _get_users_to_notify(self):
        """Get list of users to notify based on invoice type"""
        users_to_notify = []

        if self.move_type == 'out_invoice':
            # For customer invoices, notify the salesperson/invoice user
            if self.invoice_user_id:
                users_to_notify.append(self.invoice_user_id)
            elif self.invoice_origin:
                # Try to find the salesperson from the sale order
                sale_order = self.env['sale.order'].search([
                    ('name', '=', self.invoice_origin)
                ], limit=1)
                if sale_order and sale_order.user_id:
                    users_to_notify.append(sale_order.user_id)
        else:
            # For vendor bills, notify accounting users
            if self.invoice_user_id:
                users_to_notify.append(self.invoice_user_id)
            else:
                # Notify accounting manager or users with billing rights
                accounting_users = self.env.ref('account.group_account_invoice',
                                                raise_if_not_found=False)
                if accounting_users:
                    users_to_notify.extend(accounting_users.users[:2])

        # Remove duplicates
        users_to_notify = list(set(users_to_notify))

        # Fallback to current user if no one found
        if not users_to_notify:
            users_to_notify = [self.env.user]

        return users_to_notify

    def _send_inbox_notification(self, user, doc_type, time_desc):
        """Send notification to user's inbox (bell icon)"""
        self.ensure_one()

        # Get or create the notification subtype
        subtype = self.env.ref('payment_due_notifications.mt_payment_due_reminder',
                               raise_if_not_found=False)

        if not subtype:
            # Fallback to default comment subtype
            subtype = self.env.ref('mail.mt_comment')

        # Create notification message
        body = f"""
            <div style="padding: 10px; background-color: #fff3e0; border-left: 4px solid #FF9800; margin: 10px 0;">
                <p style="margin: 0 0 10px 0;">
                    <strong style="color: #FF9800;">⚠️ Payment Due {time_desc}</strong>
                </p>
                <p style="margin: 5px 0;">
                    <strong>{doc_type}:</strong> {self.name}
                </p>
                <p style="margin: 5px 0;">
                    <strong>Customer:</strong> {self.partner_id.name}
                </p>
                <p style="margin: 5px 0;">
                    <strong>Amount Due:</strong> 
                    <span style="color: #d32f2f; font-size: 16px;">
                        {self.amount_residual} {self.currency_id.name}
                    </span>
                </p>
                <p style="margin: 5px 0;">
                    <strong>Due Date:</strong> {self.invoice_date_due}
                </p>
            </div>
        """

        # Post message with notification
        self.message_post(
            body=body,
            subject=f'Payment Due Reminder: {self.name}',
            message_type='notification',
            subtype_id=subtype.id,
            partner_ids=[user.partner_id.id],
        )

        # Send bus notification for real-time popup
        self.env['bus.bus']._sendone(
            user.partner_id,
            'simple_notification',
            {
                'title': '⚠️ Payment Due Reminder',
                'message': f'{doc_type} {self.name} is due {time_desc} ({self.invoice_date_due})',
                'type': 'warning',
                'sticky': True,
            }
        )

    def _create_payment_activity(self, user, time_desc):
        """Create activity for payment tracking"""
        self.ensure_one()

        doc_type = 'Customer Invoice' if self.move_type == 'out_invoice' else 'Vendor Bill'

        self.activity_schedule(
            'mail.mail_activity_data_warning',
            summary=f'Payment Due: {self.name}',
            note=f"""
                <p><strong>Payment Due Reminder</strong></p>
                <p>{doc_type} <strong>{self.name}</strong> is due {time_desc}!</p>
                <ul>
                    <li>Partner: {self.partner_id.name}</li>
                    <li>Amount Due: {self.amount_residual} {self.currency_id.name}</li>
                    <li>Due Date: {self.invoice_date_due}</li>
                </ul>
                <p>Please ensure payment is processed on time.</p>
            """,
            user_id=user.id,
            date_deadline=self.invoice_date_due,
        )

    def _send_payment_due_email(self, time_desc):
        """Send email notification for payment due"""
        self.ensure_one()

        template = self.env.ref('payment_due_notifications.email_template_payment_due',
                                raise_if_not_found=False)

        if template:
            try:
                # Pass time description to template context
                ctx = dict(self.env.context, time_desc=time_desc)
                template.with_context(ctx).send_mail(self.id, force_send=False)
            except Exception as e:
                _logger.error(f'Failed to send payment due email for {self.name}: {str(e)}')

    def action_post(self):
        """Reset notification flag when invoice is posted"""
        res = super(AccountMove, self).action_post()
        self.notification_sent = False
        self.last_notification_check = False
        return res

    def action_test_notification(self):
        """Manual button to test notification"""
        self.ensure_one()
        config = self.env['payment.notification.config'].get_config()
        self._send_payment_due_notification(config)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Test Notification Sent',
                'message': f'Payment notification sent for {self.name}',
                'type': 'success',
                'sticky': False,
            }
        }