from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    amount_untaxed_pkr = fields.Monetary(
        string='Untaxed Amount in PKR',
        compute='_compute_pkr_totals',
        currency_field='company_currency_id'
    )
    amount_tax_pkr = fields.Monetary(
        string='Tax in PKR',
        compute='_compute_pkr_totals',
        currency_field='company_currency_id'
    )
    amount_total_pkr = fields.Monetary(
        string='Total in PKR',
        compute='_compute_pkr_totals',
        currency_field='company_currency_id'
    )
    amount_residual_pkr = fields.Monetary(
        string='Amount Due in PKR',
        compute='_compute_pkr_totals',
        currency_field='company_currency_id'
    )
    amount_total_words_pkr = fields.Char(
        string='Total Amount in Words (PKR)',
        compute='_compute_amount_total_words_pkr'
    )

    @api.depends('amount_untaxed', 'amount_tax', 'amount_total', 'amount_residual', 'currency_id', 'invoice_date')
    def _compute_pkr_totals(self):
        for move in self:
            company_currency = move.company_id.currency_id
            date = move.date or fields.Date.today()

            # Helper function to reduce repetitive code
            def convert_to_pkr(amount):
                return move.currency_id._convert(
                    amount, company_currency, move.company_id, date
                )

            move.amount_untaxed_pkr = convert_to_pkr(move.amount_untaxed)
            move.amount_tax_pkr = convert_to_pkr(move.amount_tax)
            move.amount_total_pkr = convert_to_pkr(move.amount_total)
            move.amount_residual_pkr = convert_to_pkr(move.amount_residual)

    @api.depends('amount_total_pkr')
    def _compute_amount_total_words_pkr(self):
        for move in self:
            # Using Odoo's built-in currency tool to convert the PKR amount to text
            move.amount_total_words_pkr = move.company_id.currency_id.amount_to_text(move.amount_total_pkr)