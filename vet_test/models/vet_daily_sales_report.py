import logging
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class VetDailySalesReportWizard(models.TransientModel):
    _name = 'vet.daily.sales.report.wizard'
    _description = 'Daily Sales Report Wizard'

    company_id = fields.Many2one(
        'res.company',
        string='Branch',
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )

    invoice_seq_from = fields.Char(
        string='Invoice From',
        help='Enter invoice number (e.g., 001 or 2025/00230)'
    )

    invoice_seq_to = fields.Char(
        string='Invoice To',
        help='Enter invoice number (e.g., 010 or 2026/00010)'
    )

    report_type = fields.Selection([
        ('detailed', 'Detailed Report'),
        ('summary', 'Summary Report')
    ], string='Report Type', default='detailed', required=True)

    def action_generate_report(self):
        self.ensure_one()

        # Build domain for invoices
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('company_id', '=', self.company_id.id)
        ]

        # Search all invoices first
        invoices = self.env['account.move'].search(domain, order='name')

        # Filter by invoice range if specified
        if self.invoice_seq_from or self.invoice_seq_to:
            invoices = self._filter_invoices_by_range(
                invoices,
                self.invoice_seq_from,
                self.invoice_seq_to
            )

        if not invoices:
            raise UserError('No invoices found for the selected invoice range.')

        # Log for debugging
        _logger.info(f"Found {len(invoices)} invoices: {invoices.mapped('name')}")

        # Generate report - pass invoice IDs in data
        return self.env.ref('vet_test.action_report_daily_sales').report_action(
            self,
            data={
                'invoice_ids': invoices.ids,
                'company_id': self.company_id.id,
                'report_type': self.report_type,
                'invoice_from': self.invoice_seq_from or '',
                'invoice_to': self.invoice_seq_to or '',
            }
        )

    def _filter_invoices_by_range(self, invoices, from_seq, to_seq):
        """Filter invoices by sequence range, handling different formats."""
        filtered = invoices

        if from_seq:
            filtered = filtered.filtered(
                lambda inv: self._invoice_matches_from(inv.name, from_seq)
            )

        if to_seq:
            filtered = filtered.filtered(
                lambda inv: self._invoice_matches_to(inv.name, to_seq)
            )

        return filtered

    def _invoice_matches_from(self, invoice_name, from_seq):
        """Check if invoice_name is >= from_seq"""
        inv_normalized = self._normalize_invoice_number(invoice_name)
        from_normalized = self._normalize_invoice_number(from_seq)

        # Extract year and sequence number
        inv_year = self._extract_year(inv_normalized)
        from_year = self._extract_year(from_normalized)
        inv_seq = self._extract_sequence_number(inv_normalized)
        from_seq_num = self._extract_sequence_number(from_normalized)

        # If from_seq doesn't have a year, use current year
        if not from_year:
            current_year = str(datetime.now().year)
            # Only match invoices from current year
            if inv_year != current_year:
                return False
        else:
            # If years don't match, compare years
            if inv_year != from_year:
                return inv_year >= from_year

        # Same year or both without year - compare sequence numbers
        return self._compare_invoice_numbers(inv_seq, from_seq_num) >= 0

    def _invoice_matches_to(self, invoice_name, to_seq):
        """Check if invoice_name is <= to_seq"""
        inv_normalized = self._normalize_invoice_number(invoice_name)
        to_normalized = self._normalize_invoice_number(to_seq)

        # Extract year and sequence number
        inv_year = self._extract_year(inv_normalized)
        to_year = self._extract_year(to_normalized)
        inv_seq = self._extract_sequence_number(inv_normalized)
        to_seq_num = self._extract_sequence_number(to_normalized)

        # If to_seq doesn't have a year, use current year
        if not to_year:
            current_year = str(datetime.now().year)
            # Only match invoices from current year
            if inv_year != current_year:
                return False
        else:
            # If years don't match, compare years
            if inv_year != to_year:
                return inv_year <= to_year

        # Same year or both without year - compare sequence numbers
        return self._compare_invoice_numbers(inv_seq, to_seq_num) <= 0

    def _normalize_invoice_number(self, invoice_num):
        """
        Normalize invoice number for comparison.
        Examples:
        - 'INV/2026/00007' -> '2026/00007'
        - '2026/00007' -> '2026/00007'
        - '00007' -> '00007'
        """
        if not invoice_num:
            return ''

        invoice_num = str(invoice_num).strip()

        # Remove common prefixes like 'INV/'
        if invoice_num.startswith('INV/'):
            invoice_num = invoice_num[4:]

        return invoice_num

    def _extract_sequence_number(self, invoice_num):
        """
        Extract the sequence number from invoice.
        Examples:
        - '2026/00007' -> '00007'
        - '00007' -> '00007'
        - '2025/00230' -> '00230'
        """
        if not invoice_num:
            return ''

        # If it contains '/', take the part after the last '/'
        if '/' in invoice_num:
            return invoice_num.split('/')[-1]

        # Otherwise return as is
        return invoice_num

    def _extract_year(self, invoice_num):
        """
        Extract the year from invoice number.
        Examples:
        - '2026/00007' -> '2026'
        - '00007' -> ''
        - '2025/00230' -> '2025'
        """
        if not invoice_num:
            return ''

        # If it contains '/', take the first part (year)
        if '/' in invoice_num:
            return invoice_num.split('/')[0]

        # No year present
        return ''

    def _compare_invoice_numbers(self, inv1, inv2):
        """
        Compare two sequence numbers intelligently.
        Returns: -1 if inv1 < inv2, 0 if equal, 1 if inv1 > inv2

        Handles:
        - Pure numbers: '00007' vs '00001' (numeric comparison)
        """
        if not inv1 and not inv2:
            return 0
        if not inv1:
            return -1
        if not inv2:
            return 1

        # Check if both are pure numbers (with or without leading zeros)
        if inv1.isdigit() and inv2.isdigit():
            # Compare numerically
            num1 = int(inv1)
            num2 = int(inv2)
            if num1 < num2:
                return -1
            elif num1 > num2:
                return 1
            else:
                return 0

        # Otherwise use lexical comparison
        if inv1 < inv2:
            return -1
        elif inv1 > inv2:
            return 1
        else:
            return 0


class ReportDailySales(models.AbstractModel):
    _name = 'report.vet_test.report_daily_sales_document'
    _description = 'Daily Sales Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        _logger.info(f"_get_report_values called with docids={docids}, data={data}")

        if not data or not data.get('invoice_ids'):
            raise UserError('No invoices provided for report generation.')

        # Get the invoices from data
        invoice_ids = data.get('invoice_ids', [])
        invoices = self.env['account.move'].browse(invoice_ids)

        if not invoices:
            raise UserError('No invoices found with the provided IDs.')

        company = self.env['res.company'].browse(data.get('company_id'))

        # Prepare report data
        report_data = self._prepare_report_data(invoices)

        _logger.info(
            f"Report data prepared: services={len(report_data.get('services_by_type', {}).get('service', []))}, "
            f"vaccines={len(report_data.get('services_by_type', {}).get('vaccine', []))}, "
            f"tests={len(report_data.get('services_by_type', {}).get('test', []))}")
        _logger.info(f"Total sales: {report_data.get('total_sales')}")

        return {
            'doc_ids': docids,
            'doc_model': 'vet.daily.sales.report.wizard',
            'docs': self.env['vet.daily.sales.report.wizard'].browse(docids),
            'data': data,
            'company': company,
            'invoices': invoices,
            'report_data': report_data,
            'report_type': data.get('report_type', 'detailed'),
        }

    def _prepare_report_data(self, invoices):
        """Prepare all data needed for the report."""

        # Initialize data structures
        service_data = {}
        payment_data = {

        }

        total_sales = 0.0
        total_discount = 0.0
        total_invoices = len(invoices)
        discount_invoice_count = 0

        # Invoice payment status tracking
        paid_invoices = {'count': 0, 'amount': 0.0}
        partial_invoices = {'count': 0, 'amount': 0.0}
        unpaid_invoices = {'count': 0, 'amount': 0.0}

        # Counters for different service types
        service_counts = {
            'service': 0,
            'vaccine': 0,
            'test': 0,
        }

        # Process each invoice
        for invoice in invoices:
            # Skip cancelled invoices
            if invoice.state == 'cancel':
                continue

            invoice_total = invoice.amount_total
            total_sales += invoice_total

            # Determine payment status
            if invoice.payment_state == 'paid':
                paid_invoices['count'] += 1
                paid_invoices['amount'] += invoice_total
            elif invoice.payment_state == 'partial':
                partial_invoices['count'] += 1
                partial_invoices['amount'] += invoice_total
            else:  # not_paid or in_payment
                unpaid_invoices['count'] += 1
                unpaid_invoices['amount'] += invoice_total

            # Check if invoice has any discount
            invoice_has_discount = False
            # Calculate discounts from invoice lines
            for line in invoice.invoice_line_ids:
                # Get service information
                product_name = line.product_id.name if line.product_id else line.name

                # Check if product is a discount product (negative price or 'discount' in name)
                if line.price_subtotal < 0 or (product_name and 'discount' in product_name.lower()):
                    # This is a discount line - add absolute value to total discount
                    discount_amount = abs(line.price_subtotal)
                    total_discount += discount_amount
                    invoice_has_discount = True
                    _logger.info(
                        f"Invoice {invoice.name}, Discount Product Line '{product_name}': amount={discount_amount}")
                    # Skip adding this to service data - DISCOUNT LINES ARE NOT COUNTED AS SERVICES
                    continue

                # Calculate inline discount amount from the discount percentage field
                if line.discount > 0:
                    # Calculate the discount amount: (price * qty) * (discount% / 100)
                    line_discount_amount = (line.price_unit * line.quantity) * (line.discount / 100.0)
                    total_discount += line_discount_amount
                    invoice_has_discount = True
                    _logger.info(
                        f"Invoice {invoice.name}, Line '{product_name}': discount={line.discount}%, amount={line_discount_amount}")

                # Try to find related service (only for non-discount lines)
                service_type = 'service'  # default
                if line.product_id:
                    # Find service by product
                    service = self.env['vet.service'].search([
                        ('product_id', '=', line.product_id.id)
                    ], limit=1)

                    if service:
                        service_type = service.service_type
                        # Only count non-discount items
                        service_counts[service_type] += 1

                # Group by service name (only non-discount items)
                if product_name not in service_data:
                    service_data[product_name] = {
                        'qty': 0.0,
                        'amount': 0.0,
                        'discount': 0.0,
                        'service_type': service_type,
                        'lines': []
                    }

                service_data[product_name]['qty'] += line.quantity
                service_data[product_name]['amount'] += line.price_subtotal

                # Add discount amount for this line
                if line.discount > 0:
                    line_discount = (line.price_unit * line.quantity) * (line.discount / 100.0)
                    service_data[product_name]['discount'] += line_discount

                service_data[product_name]['lines'].append({
                    'product': product_name,
                    'quantity': line.quantity,
                    'price_unit': line.price_unit,
                    'subtotal': line.price_subtotal,
                })

            # Count invoices with discounts
            if invoice_has_discount:
                discount_invoice_count += 1

            # Process payments for this invoice
            payment_moves = invoice.line_ids.filtered(
                lambda l: l.account_id.reconcile
            ).mapped('matched_credit_ids.credit_move_id.move_id') | \
                            invoice.line_ids.filtered(
                                lambda l: l.account_id.reconcile
                            ).mapped('matched_debit_ids.debit_move_id.move_id')

            for payment_move in payment_moves:
                if payment_move.state != 'posted' or payment_move.move_type != 'entry':
                    continue

                journal_name = payment_move.journal_id.name
                credit_lines = payment_move.line_ids.filtered(lambda l: l.credit > 0)

                for credit_line in credit_lines:
                    amount = credit_line.credit
                    if journal_name not in payment_data:
                        payment_data[journal_name] = 0.0
                    payment_data[journal_name] += amount

        # Ensure "Online" payment method exists with 0 if not present
        if 'Online' not in payment_data:
            payment_data['Online'] = 0.0

        # Group services by type
        services_by_type = {
            'service': [],
            'vaccine': [],
            'test': [],
        }

        for service_name, service_info in service_data.items():
            service_type = service_info['service_type']
            services_by_type[service_type].append({
                'name': service_name,
                'qty': service_info['qty'],
                'amount': service_info['amount'],
                'discount': service_info['discount'],
            })

        # Sort each service type by amount (descending)
        for stype in services_by_type:
            services_by_type[stype].sort(key=lambda x: x['amount'], reverse=True)

        # Calculate total paid from payment data
        total_paid = sum(payment_data.values())

        return {
            'services_by_type': services_by_type,
            'service_counts': service_counts,
            'payment_data': payment_data,
            'total_sales': total_sales,
            'total_gross': total_sales + total_discount,
            'total_discount': total_discount,
            'discount_invoice_count': discount_invoice_count,
            'total_invoices': total_invoices,
            'total_paid': total_paid,
            'paid_invoices': paid_invoices,
            'partial_invoices': partial_invoices,
            'unpaid_invoices': unpaid_invoices,
            'invoice_range': f"{invoices[0].name} to {invoices[-1].name}" if invoices else '',
        }