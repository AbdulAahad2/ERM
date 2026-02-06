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

    visit_id = fields.Many2one('vet.animal.visit', string="Animal Visit", index=True)
    animal_display_name = fields.Char(
        string="Animal Display Name",
        compute="_compute_animal_display_name",
        store=True
    )
    vet_owner_id = fields.Many2one(
        'vet.animal.owner',
        string="Vet Owner",
        compute='_compute_vet_owner_id',
        store=True,
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
        store=True,
    )
    invoice_unpaid_balance = fields.Monetary(
        string="Invoice Unpaid",
        compute="_compute_invoice_unpaid_balance",
        store=True,
        currency_field="currency_id",
    )
    
    extract_error_message = fields.Char(string="Extract Error Message")
    extract_document_uuid = fields.Char()
    extract_state = fields.Char()
    extract_attachment_id = fields.Many2one('ir.attachment')
    extract_can_show_send_button = fields.Boolean()
    extract_can_show_banners = fields.Boolean()

    invoice_year = fields.Integer(
        string="Invoice Year",
        compute='_compute_invoice_year',
        store=True,
        readonly=True,
        index=True,
    )
    
    invoice_seq_from = fields.Char(
        string="Invoice From",
        store=False,
        search='_search_invoice_seq_from',
        help="Enter sequence number (e.g., 001) for current year or full format (e.g., 2025/00230)"
    )
    invoice_seq_to = fields.Char(
        string="Invoice To",
        store=False,
        search='_search_invoice_seq_to',
        help="Enter sequence number (e.g., 010) for current year or full format (e.g., 2026/00010)"
    )

    @api.depends('visit_id', 'visit_id.owner_id')
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
        string="Card",
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

    display_amount_total = fields.Monetary(
        string="Display Total",
        compute="_compute_display_amount_total",
        currency_field="currency_id",
        store=False,
    )

    @api.depends('amount_total', 'state')
    def _compute_display_amount_total(self):
        for move in self:
            if move.state == 'cancel':
                move.display_amount_total = 0.0
            else:
                move.display_amount_total = move.amount_total

    @api.depends('name')
    def _compute_invoice_year(self):
        """Extract year from invoice name (e.g., INV/2025/00001)"""
        for move in self:
            if move.name and '/' in move.name:
                parts = move.name.split('/')
                # Try to find year in the invoice name parts
                year_found = False
                for part in parts:
                    if part.isdigit() and len(part) == 4 and 2000 <= int(part) <= 2100:
                        move.invoice_year = int(part)
                        year_found = True
                        break
                
                if not year_found:
                    # If no year found in name, use invoice_date year or current year
                    move.invoice_year = move.invoice_date.year if move.invoice_date else fields.Date.today().year
            else:
                move.invoice_year = move.invoice_date.year if move.invoice_date else fields.Date.today().year
    
    def _parse_invoice_input(self, value):
        """
        Parse invoice input to extract year and sequence number.
        Returns tuple (year, sequence_number, has_year_format)
        
        Examples:
        - "001" or "1" -> (2026, 1, False)  # current year, no year in format
        - "2025/00230" -> (2025, 230, True)  # has year in format
        - "2026/10" -> (2026, 10, True)
        """
        if not value:
            return None, None, False
        
        value = str(value).strip()
        has_year_format = '/' in value
        
        # Check if format includes year (contains /)
        if has_year_format:
            parts = value.split('/')
            try:
                # Find year and sequence in parts
                year = None
                seq = None
                
                for part in parts:
                    part_clean = part.strip()
                    if part_clean.isdigit():
                        num = int(part_clean)
                        # If it's a 4-digit number between 2000-2100, it's a year
                        if 2000 <= num <= 2100:
                            year = num
                        else:
                            # Otherwise it's the sequence number
                            seq = num
                
                if year and seq is not None:
                    return year, seq, True
            except:
                pass
        
        # Simple number format - assume current year
        try:
            seq = int(value.lstrip('0') if value != '0' else '0')
            current_year = fields.Date.today().year
            return current_year, seq, False
        except:
            return None, None, False
    
    def _search_invoice_seq_from(self, operator, value):
        """
        Smart search for invoice sequence 'from' value.
        Handles:
        - Simple numbers: "001", "10" -> filters current year only
        - Year/Sequence: "2025/00230" -> filters from this point forward (cross-year)
        """
        if not value:
            return []
        
        year, seq, has_year_format = self._parse_invoice_input(value)
        
        if year is None or seq is None:
            return []
        
        # If it's a simple number (current year), restrict to current year only
        if not has_year_format:
            return [
                ('invoice_year', '=', year),
                ('invoice_sequence_number', '>=', seq)
            ]
        
        # If it includes year (e.g., 2025/00230), allow cross-year search
        # Logic: (year > from_year) OR (year = from_year AND seq >= from_seq)
        return [
            '|',
            ('invoice_year', '>', year),
            '&',
            ('invoice_year', '=', year),
            ('invoice_sequence_number', '>=', seq)
        ]
    
    def _search_invoice_seq_to(self, operator, value):
        """
        Smart search for invoice sequence 'to' value.
        Handles:
        - Simple numbers: "010", "10" -> filters current year only
        - Year/Sequence: "2026/00010" -> filters up to this point (cross-year)
        """
        if not value:
            return []
        
        year, seq, has_year_format = self._parse_invoice_input(value)
        
        if year is None or seq is None:
            return []
        
        # If it's a simple number (current year), restrict to current year only
        if not has_year_format:
            return [
                ('invoice_year', '=', year),
                ('invoice_sequence_number', '<=', seq)
            ]
        
        # If it includes year (e.g., 2026/00010), allow cross-year search
        # Logic: (year < to_year) OR (year = to_year AND seq <= to_seq)
        return [
            '|',
            ('invoice_year', '<', year),
            '&',
            ('invoice_year', '=', year),
            ('invoice_sequence_number', '<=', seq)
        ]
    
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
                    # Get the last part which should be the sequence number
                    seq = int(parts[-1])
                    move.invoice_sequence_number = seq
                except:
                    move.invoice_sequence_number = 0
            else:
                move.invoice_sequence_number = 0
                
    @api.depends('amount_residual', 'state')
    def _compute_invoice_unpaid_balance(self):
        for move in self:
            if move.state == 'cancel':
                move.invoice_unpaid_balance = 0.0
            else:
                move.invoice_unpaid_balance = move.amount_residual

    @api.depends('partner_id', 'move_type', 'state', 'payment_state')
    def _compute_owner_unpaid_balance(self):
        # Quick exit for cancelled invoices
        for move in self.filtered(lambda m: m.state == 'cancel'):
            move.owner_unpaid_balance = 0.0
        
        # Get only non-cancelled invoices
        active_moves = self.filtered(lambda m: m.state != 'cancel' and m.move_type == 'out_invoice')
        if not active_moves:
            return
        
        # Get unique partners
        partners = active_moves.mapped('partner_id').filtered(lambda p: p)
        if not partners:
            for move in active_moves:
                move.owner_unpaid_balance = 0.0
            return
        
        self.env.cr.execute("""
            SELECT partner_id, SUM(amount_residual) 
            FROM account_move 
            WHERE partner_id IN %s 
                AND move_type = 'out_invoice' 
                AND state = 'posted' 
                AND payment_state IN ('not_paid', 'partial')
            GROUP BY partner_id
        """, (tuple(partners.ids),))
        
        partner_balances = dict(self.env.cr.fetchall())
        
        # Assign balances
        for move in active_moves:
            if move.partner_id:
                move.owner_unpaid_balance = partner_balances.get(move.partner_id.id, 0.0)
            else:
                move.owner_unpaid_balance = 0.0
            
    @api.depends("visit_id", "visit_id.animal_id", "visit_id.animal_id.name")
    def _compute_animal_display_name(self):
        for move in self:
            move.animal_display_name = move.visit_id.animal_id.name if move.visit_id and move.visit_id.animal_id else ""

    @api.depends("amount_total", "amount_residual", "state")
    def _compute_amount_paid(self):
        for move in self:
            if move.state == 'cancel':
                move.amount_paid = 0.0
            else:
                move.amount_paid = move.amount_total - move.amount_residual

    @api.depends('line_ids.account_id', 'line_ids.move_id', 'line_ids.reconciled', 'amount_total', 'state')
    def _compute_dashboard_stored(self):
        for rec in self:
            rec.dashboard_total_cash = 0.0
            rec.dashboard_total_bank = 0.0
            rec.dashboard_total_online = 0.0

            if rec.state == 'cancel':
                continue

            if rec.state != 'posted' or rec.move_type not in ('out_invoice', 'out_receipt'):
                continue

            payment_moves = rec.line_ids.filtered(lambda l: l.account_id.reconcile).mapped('matched_credit_ids.credit_move_id.move_id') \
                          | rec.line_ids.filtered(lambda l: l.account_id.reconcile).mapped('matched_debit_ids.debit_move_id.move_id')

            for payment_move in payment_moves:
                if payment_move.state != 'posted' or payment_move.move_type != 'entry':
                    continue

                credit_lines = payment_move.line_ids.filtered(lambda l: l.credit > 0 and l.account_id)
                if not credit_lines:
                    continue

                for credit_line in credit_lines:
                    journal = payment_move.journal_id
                    amount = credit_line.credit

                    if journal.type == 'cash':
                        rec.dashboard_total_cash += amount
                    elif journal.type == 'bank':
                        if any(tag in (journal.name or '').lower() for tag in ['online']):
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
        
        moves = super(AccountMove, self).create(vals_list)
        return moves

    def action_post(self):
        """Override to update owner_unpaid_balance for related invoices"""
        # Collect partners from customer invoices being posted
        partners_to_update = self.filtered(
            lambda m: m.move_type == 'out_invoice' and m.partner_id
        ).mapped('partner_id')
        
        # Call parent method to post the invoices
        res = super().action_post()
        
        # After posting, invalidate owner_unpaid_balance cache for all invoices
        # of these partners so it recalculates on next access
        if partners_to_update:
            # Find all invoices for these partners
            partner_invoices = self.env['account.move'].search([
                ('partner_id', 'in', partners_to_update.ids),
                ('move_type', '=', 'out_invoice')
            ])
            
            # Invalidate the computed field cache
            # This forces Odoo to recalculate when accessed
            partner_invoices.invalidate_recordset(['owner_unpaid_balance'])
            
            _logger.info(
                "Invalidated owner_unpaid_balance for %d invoices of %d partners",
                len(partner_invoices), len(partners_to_update)
            )
        
        return res

    def button_cancel(self):
        """Override to update owner_unpaid_balance when canceling invoices"""
        # Collect partners before canceling
        partners_to_update = self.filtered(
            lambda m: m.move_type == 'out_invoice' and m.partner_id
        ).mapped('partner_id')
        
        # Call parent method
        res = super().button_cancel()
        
        # Invalidate cache after canceling
        if partners_to_update:
            partner_invoices = self.env['account.move'].search([
                ('partner_id', 'in', partners_to_update.ids),
                ('move_type', '=', 'out_invoice')
            ])
            partner_invoices.invalidate_recordset(['owner_unpaid_balance'])
            
            _logger.info(
                "Invalidated owner_unpaid_balance after canceling %d invoices",
                len(self)
            )
        
        return res

    def _compute_global_totals(self, records):
        total_cash = total_bank = total_online = total_unpaid = 0.0

        records = records.filtered(lambda r: r.state != 'cancel')
        
        if not records:
            return {
                'dashboard_total_cash': 0.0,
                'dashboard_total_bank': 0.0,
                'dashboard_total_online': 0.0,
                'invoice_unpaid_balance_total': 0.0,
            }

        # Use already computed stored fields instead of recalculating
        total_cash = sum(records.mapped('dashboard_total_cash'))
        total_bank = sum(records.mapped('dashboard_total_bank'))
        total_online = sum(records.mapped('dashboard_total_online'))
        total_unpaid = sum(records.mapped('invoice_unpaid_balance'))

        return {
            'dashboard_total_cash': total_cash,
            'dashboard_total_bank': total_bank,
            'dashboard_total_online': total_online,
            'invoice_unpaid_balance_total': total_unpaid,
        }
        
    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        # Replace 'display_amount_total' with 'amount_total' in fields if present
        if 'display_amount_total' in fields:
            fields = [f if f != 'display_amount_total' else 'amount_total' for f in fields]
        
        res = super().read_group(domain, fields, groupby,
                                 offset=offset, limit=limit, orderby=orderby, lazy=lazy)
        
        # Check if custom fields are requested
        custom_fields = {'dashboard_total_cash', 'dashboard_total_bank', 'dashboard_total_online', 
                        'invoice_unpaid_balance', 'amount_total', 'owner_unpaid_balance'}
        if not any(f in fields for f in custom_fields):
            return res
    
        for group in res:
            if '__domain' not in group:
                continue
            
            group_records = self.search(group['__domain'])
            group_totals = self._compute_global_totals(group_records)
            
            active_records = group_records.filtered(lambda r: r.state != 'cancel')
            
            # For amount_total, exclude cancelled invoices from sum
            amount_total_sum = sum(active_records.mapped('amount_total')) or 0.0
            
            group.update({
                'dashboard_total_cash': group_totals['dashboard_total_cash'],
                'dashboard_total_bank': group_totals['dashboard_total_bank'],
                'dashboard_total_online': group_totals['dashboard_total_online'],
                'invoice_unpaid_balance': group_totals['invoice_unpaid_balance_total'],
                'amount_total': amount_total_sum,  # Override with filtered sum
                'owner_unpaid_balance': sum(active_records.mapped('owner_unpaid_balance')) or 0.0,
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

    def init(self):
        # Index for partner + payment state lookups
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_account_move_partner_payment 
            ON account_move(partner_id, payment_state, state) 
            WHERE move_type = 'out_invoice' AND state = 'posted';
        """)
        
        # Index for visit lookups
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_account_move_visit 
            ON account_move(visit_id) 
            WHERE visit_id IS NOT NULL;
        """)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        """Override to update owner_unpaid_balance after payment"""
        res = super().action_post()
        
        for payment in self:
            invoices = payment.invoice_ids
            if invoices and payment.move_id:
                # Reconcile lines
                lines_to_reconcile = payment.move_id.line_ids | invoices.mapped('line_ids')
                if lines_to_reconcile:
                    try:
                        lines_to_reconcile.reconcile()
                    except Exception as e:
                        _logger.warning("Reconciliation failed: %s", e)
                
                # Invalidate owner_unpaid_balance for all partner invoices
                partners = invoices.mapped('partner_id')
                if partners:
                    partner_invoices = self.env['account.move'].search([
                        ('partner_id', 'in', partners.ids),
                        ('move_type', '=', 'out_invoice')
                    ])
                    partner_invoices.invalidate_recordset(['owner_unpaid_balance'])
                    _logger.info(
                        "Invalidated owner_unpaid_balance for %d invoices after payment",
                        len(partner_invoices)
                    )
        
        return res
