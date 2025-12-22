# -*- coding: utf-8 -*-
import logging
import re
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ===================== BASIC FIELDS =====================
    visit_id = fields.Many2one('vet.animal.visit', string="Animal Visit")
    animal_display_name = fields.Char(
        string="Animal Display Name",
        compute="_compute_animal_display_name",
        store=True
    )
    vet_owner_id = fields.Many2one(
        'vet.animal.owner',
        string="Vet Owner",
        compute='_compute_vet_owner_id',
        store=False,
        readonly=True
    )
    amount_paid = fields.Monetary(
        string="Amount Paid",
        compute="_compute_amount_paid",
        currency_field="currency_id",
        store=True
    )
    owner_unpaid_balance = fields.Float(
        string="Owner Unpaid Balance",
        compute="_compute_owner_unpaid_balance",
        store=False,
    )
    invoice_unpaid_balance = fields.Monetary(
        string="Invoice Unpaid",
        compute="_compute_invoice_unpaid_balance",
        store=True,
        currency_field="currency_id",
    )
    
    # Extract / digitization (placeholders)
    extract_error_message = fields.Char(string="Extract Error Message")
    extract_document_uuid = fields.Char()
    extract_state = fields.Char()
    extract_attachment_id = fields.Many2one('ir.attachment')
    extract_can_show_send_button = fields.Boolean()
    extract_can_show_banners = fields.Boolean()

    # ===================== RANGE FILTER FIELDS =====================
    invoice_seq_from = fields.Integer(
        string="Invoice From",
        store=False,
        search='_search_invoice_seq_from'
    )
    invoice_seq_to = fields.Integer(
        string="Invoice To",
        store=False,
        search='_search_invoice_seq_to'
    )

    # ===================== DASHBOARD TOTALS =====================
    def _compute_vet_owner_id(self):
        for move in self:
            move.vet_owner_id = move.visit_id.owner_id if move.visit_id else False
            
    dashboard_total_all = fields.Monetary(
        compute="_compute_dashboard_non_stored",
        currency_field="currency_id",
        string="Total Invoiced",
        store=False,
        compute_sudo=False
    )
    dashboard_total_cash = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Cash Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_bank = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Bank Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_online = fields.Monetary(
        compute="_compute_dashboard_stored",
        currency_field="currency_id",
        string="Online/Credit Payments",
        store=True,
        compute_sudo=True
    )
    dashboard_total_discount = fields.Monetary(
        compute="_compute_dashboard_non_stored",
        currency_field="currency_id",
        string="Discount (on Cash)",
        store=False,
        compute_sudo=False
    )

    payment_journal_id = fields.Many2one(
        'account.journal',
        related="visit_id.journal_id",
        store=True,
        readonly=True,
        string="Payment Journal",
        help="Journal used for payment in the related visit"
    )

    invoice_sequence_number = fields.Integer(
        string="Invoice Sequence Number",
        compute='_compute_invoice_sequence_number',
        store=True,
        readonly=True,
    )

    payment_journal_type = fields.Selection(
        [('cash', 'Cash'), ('bank', 'Bank')],
        string="Payment Type",
        compute="_compute_payment_journal_type",
        store=True,
        help="Type of payment journal (Cash or Bank)"
    )

    # ===================== SEARCH METHODS FOR RANGE =====================
    def _search_invoice_seq_from(self, operator, value):
        """Search method for invoice_seq_from field"""
        if operator == '=' and value:
            return [('invoice_sequence_number', '>=', value)]
        return []

    def _search_invoice_seq_to(self, operator, value):
        """Search method for invoice_seq_to field"""
        if operator == '=' and value:
            return [('invoice_sequence_number', '<=', value)]
        return []

    # ===================== COMPUTE METHODS =====================
    
    @api.depends('payment_journal_id', 'payment_journal_id.type')
    def _compute_payment_journal_type(self):
        for move in self:
            if move.payment_journal_id:
                move.payment_journal_type = move.payment_journal_id.type
            else:
                move.payment_journal_type = False

    @api.depends('name')
    def _compute_invoice_sequence_number(self):
        for move in self:
            if move.name and '/' in move.name:
                parts = move.name.split('/')
                try:
                    seq = int(parts[-1])  # Last part: 0001, 0123, etc.
                    move.invoice_sequence_number = seq
                except:
                    move.invoice_sequence_number = 0
            else:
                move.invoice_sequence_number = 0
                
    @api.depends('amount_residual')
    def _compute_invoice_unpaid_balance(self):
        for move in self:
            move.invoice_unpaid_balance = move.amount_residual

    @api.depends('partner_id', 'move_type', 'state', 'payment_state')
    def _compute_owner_unpaid_balance(self):
        for move in self:
            balance = 0.0
            if move.partner_id and move.move_type == 'out_invoice':
                unpaid_invoices = self.env['account.move'].search([
                    ('partner_id', '=', move.partner_id.id),
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('payment_state', 'in', ['not_paid', 'partial']),
                ])
                balance = sum(unpaid_invoices.mapped('amount_residual'))
            move.owner_unpaid_balance = balance
            
    @api.depends("visit_id", "visit_id.animal_id", "visit_id.animal_id.name")
    def _compute_animal_display_name(self):
        for move in self:
            move.animal_display_name = move.visit_id.animal_id.name if move.visit_id and move.visit_id.animal_id else ""

    @api.depends("amount_total", "amount_residual")
    def _compute_amount_paid(self):
        for move in self:
            move.amount_paid = move.amount_total - move.amount_residual

    # ===================== DASHBOARD STORED COMPUTE =====================
    @api.depends('line_ids.account_id', 'line_ids.move_id', 'line_ids.reconciled', 'amount_total')
    def _compute_dashboard_stored(self):
        for rec in self:
            rec.dashboard_total_cash = 0.0
            rec.dashboard_total_bank = 0.0
            rec.dashboard_total_online = 0.0
    
            if rec.state != 'posted' or rec.move_type not in ('out_invoice', 'out_receipt'):
                continue
    
            payment_moves = rec.line_ids.filtered(lambda l: l.account_id.reconcile).mapped('matched_credit_ids.credit_move_id.move_id') \
                          | rec.line_ids.filtered(lambda l: l.account_id.reconcile).mapped('matched_debit_ids.debit_move_id.move_id')
    
            for payment_move in payment_moves:
                if payment_move.state != 'posted' or payment_move.move_type != 'entry':
                    continue
    
                credit_line = payment_move.line_ids.filtered(lambda l: l.credit > 0 and l.account_id)
                if not credit_line:
                    continue
    
                account = credit_line.account_id
                journal = payment_move.journal_id
                amount = credit_line.credit
    
                if journal.type == 'cash':
                    rec.dashboard_total_cash += amount
                elif journal.type == 'bank':
                    if any(tag in (journal.name or '').lower() for tag in ['online', 'credit', 'card', 'pos']):
                        rec.dashboard_total_online += amount
                    else:
                        rec.dashboard_total_bank += amount
    
    @api.depends('amount_total', 'invoice_line_ids.discount', 'invoice_line_ids.price_unit', 'invoice_line_ids.quantity')
    def _compute_dashboard_non_stored(self):
        for rec in self:
            total_discount = 0.0
            for line in rec.invoice_line_ids:
                total_discount += (line.price_unit * line.quantity) * (line.discount / 100.0)
            rec.dashboard_total_all = rec.amount_total
            rec.dashboard_total_discount = total_discount

    @api.model_create_multi
    def create(self, vals_list):
        if not isinstance(vals_list, list):
            vals_list = [vals_list]
        try:
            default_account = self.env['ir.property'].sudo().get('property_account_income_categ_id', 'product.category')
            if not default_account:
                _logger.warning("No default income account found via ir.property, searching for fallback.")
                default_account = self.env['account.account'].sudo().search([('account_type', '=', 'income')], limit=1)
        except Exception:
            _logger.error("Could not retrieve default income account, falling back to first income account.")
            default_account = self.env['account.account'].sudo().search([('account_type', '=', 'income')], limit=1)
        moves = super(AccountMove, self).create(vals_list)
        return moves

    def action_post(self):
        return super().action_post()

    def _compute_global_totals(self, records):
        """Calculate Cash / Bank / Online + Invoice Unpaid totals for a recordset."""
        total_cash = total_bank = total_online = total_unpaid = 0.0

        for rec in records:
            if rec.state != 'posted' or rec.move_type not in ('out_invoice', 'out_receipt'):
                continue

            payment_moves = (
                rec.line_ids.filtered(lambda l: l.account_id.reconcile)
                .mapped('matched_credit_ids.credit_move_id.move_id')
                | rec.line_ids.filtered(lambda l: l.account_id.reconcile)
                .mapped('matched_debit_ids.debit_move_id.move_id')
            )
            for payment_move in payment_moves:
                if payment_move.state != 'posted' or payment_move.move_type != 'entry':
                    continue
                credit_line = payment_move.line_ids.filtered(lambda l: l.credit > 0 and l.account_id)
                if not credit_line:
                    continue
                journal = payment_move.journal_id
                amount = credit_line.credit
                if journal.type == 'cash':
                    total_cash += amount
                elif journal.type == 'bank':
                    if any(tag in (journal.name or '').lower() for tag in ['online', 'credit', 'card', 'pos']):
                        total_online += amount
                    else:
                        total_bank += amount

            total_unpaid += rec.invoice_unpaid_balance

        return {
            'dashboard_total_cash': total_cash,
            'dashboard_total_bank': total_bank,
            'dashboard_total_online': total_online,
            'invoice_unpaid_balance_total': total_unpaid,
        }

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        res = super().read_group(domain, fields, groupby,
                                 offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        all_records = self.search(domain)
        totals = self._compute_global_totals(all_records)

        for group in res:
            if not group.get('__domain'):
                continue
            group_records = self.search(group['__domain'])
            group_totals = self._compute_global_totals(group_records)
            group.update({
                'dashboard_total_cash': group_totals['dashboard_total_cash'],
                'dashboard_total_bank': group_totals['dashboard_total_bank'],
                'dashboard_total_online': group_totals['dashboard_total_online'],
                'amount_total': sum(group_records.mapped('amount_total')) or 0.0,
                '__count': len(group_records),
            })
        return res
        
    def action_print_visit_receipt_from_invoice(self):
        self.ensure_one()
        invoices = self if len(self) == 1 else self
        visits = invoices.mapped('visit_id').filtered(lambda v: v.exists())

        if not visits:
            origins = list(set(invoices.mapped('invoice_origin')))
            if origins:
                visits = self.env['vet.animal.visit'].search([('name', 'in', origins)])
            if not visits:
                raise UserError(_("No related visit found for this invoice."))

        return self.env.ref('vet_test.action_report_visit_receipt').report_action(visits)

    def action_register_payment(self):
        """Open the payment wizard and pre-select the journal according to visit.payment_method."""
        self.ensure_one()
        if not self.is_invoice(include_receipts=True):
            return super().action_register_payment()

        action = {
            'name': _('Register Payment'),
            'res_model': 'account.payment',
            'view_mode': 'form',
            'context': {
                'active_ids': self.ids,
                'active_model': 'account.move',
                'default_invoice_ids': [(6, 0, self.ids)],
                'default_amount': self.amount_residual,
                'default_currency_id': self.currency_id.id,
                'default_partner_id': self.commercial_partner_id.id,
                'default_communication': self.payment_reference or self.ref or self.name,
            },
            'target': 'new',
            'type': 'ir.actions.act_window',
            'views': [[False, 'form']],
        }
        return action


# ===================== ACCOUNT PAYMENT RECONCILIATION =====================
class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        res = super().action_post()
        for payment in self:
            invoices = payment.invoice_ids
            if invoices and payment.move_id:
                lines_to_reconcile = payment.move_id.line_ids | invoices.mapped('line_ids')
                if lines_to_reconcile:
                    try:
                        lines_to_reconcile.reconcile()
                    except Exception as e:
                        _logger.warning("Reconciliation failed: %s", e)
        return res

    @api.model
    def default_get(self, fields_list):
        """When the wizard is opened from an invoice, pick the correct journal."""
        res = super().default_get(fields_list)

        active_ids = self._context.get('active_ids') or (
            [self._context.get('active_id')] if self._context.get('active_id') else []
        )
        if not active_ids:
            return res

        invoices = self.env['account.move'].browse(active_ids)
        invoice = invoices[:1]
        if not invoice or not invoice.visit_id:
            return res

        visit = invoice.visit_id
        payment_method = (visit.payment_method or '').lower()

        journal = self.env['account.journal']
        if payment_method == 'cash':
            journal = self.env['account.journal'].search([('type', '=', 'cash')], limit=1)
        elif payment_method == 'bank':
            journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        elif payment_method in ('online', 'credit', 'credit_card'):
            journal = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)

        if journal:
            res['journal_id'] = journal.id
            _logger.info(
                "Auto-selected journal '%s' for payment method '%s' on invoice %s",
                journal.name, visit.payment_method, invoice.name
            )
        else:
            _logger.warning(
                "No journal found for payment method '%s' on invoice %s – fallback to default",
                visit.payment_method, invoice.name
            )
        return res
