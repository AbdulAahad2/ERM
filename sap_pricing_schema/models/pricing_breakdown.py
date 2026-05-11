from odoo import models, fields, api


class PricingBreakdownLine(models.Model):
    _name = 'pricing.breakdown.line'
    _description = 'Pricing Breakdown Line'
    _order = 'order_line_id, step'

    order_line_id = fields.Many2one(
        'sale.order.line',
        string='Order Line',
        required=True,
        ondelete='cascade',
        index=True,
    )

    step = fields.Integer(string='Step')
    condition_type = fields.Char(string='Condition Type')
    name = fields.Char(string='Description')

    base_amount = fields.Float(string='Base Amount', digits=(16, 4))
    applied_value = fields.Float(string='Rate / Value', digits=(16, 4))
    computed_amount = fields.Float(string='Step Amount', digits=(16, 4))
    running_price = fields.Float(string='Running Price', digits=(16, 4))

    tax_base = fields.Float(string='Tax Base', digits=(16, 4), help='Base amount used for tax calculation')
    tax_amount = fields.Float(string='Tax Amount', digits=(16, 4), help='Actual computed tax amount')

    # NEW: Link to the tax for proper GL posting
    tax_id = fields.Many2one(
        'account.tax',
        string='Tax',
        help='The Odoo tax record used for this tax step.'
    )

    gl_account_id = fields.Many2one(
        'account.account',
        string='GL Account',
        help='GL account from the pricing rule — posted on the invoice when the move is confirmed.'
    )
    account_key = fields.Char(string='Account Key')

    line_type = fields.Selection([
        ('condition',  'Condition'),
        ('subtotal',   'Subtotal'),
        ('tax',        'Tax'),
        ('statistical','Statistical'),
    ], string='Line Type')

    rule_type = fields.Selection([
        ('discount',   'Discount (-)'),
        ('surcharge',  'Surcharge / Margin (+)'),
        ('charge',     'Additional Charge (+)'),
        ('base_price', 'Base Price'),
    ], string='Rule Type')

    is_statistical = fields.Boolean(string='Statistical')