from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class PricingRule(models.Model):
    _name = 'pricing.rule'
    _description = 'Pricing Procedure Step'
    _order = 'step, counter, id'

    # ── Fields that only admins may change ───────────────────────────────────
    _ADMIN_ONLY_FIELDS = {
        'line_type',
        'rule_type',
        'step',
        'counter',
        'condition_type',
        'calculation_type',
        'from_step',
        'to_step',
        'is_statistical',
        'is_mandatory',
        'tax_id',
        'account_id',
        'account_key',
        'schema_id',
        'active',
    }

    name = fields.Char(string='Description', required=True)
    schema_id = fields.Many2one('pricing.schema', string='Pricing Schema', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)
    active = fields.Boolean(default=True)

    # -- SAP Procedure Columns --
    step = fields.Integer(string='Step', required=True, default=10)
    counter = fields.Integer(string='Cntr', default=0)
    condition_type = fields.Selection([
        ('PR00', 'PR00 – Base Price'),
        ('K004', 'K004 – Material Discount'),
        ('K005', 'K005 – Customer/Material Discount'),
        ('K007', 'K007 – Customer Discount'),
        ('K020', 'K020 – Price Group Discount'),
        ('HA00', 'HA00 – Order-Value Discount (%)'),
        ('HB00', 'HB00 – Order-Value Discount (Abs)'),
        ('KF00', 'KF00 – Freight'),
        ('HD00', 'HD00 – Delivery Surcharge'),
        ('SUB1', 'Subtotal 1 – Net Value Before Tax'),
        ('SUB2', 'Subtotal 2 – Custom Subtotal'),
        ('MWST', 'MWST – Output Tax'),
        ('JEXT', 'JEXT – External Tax'),
        ('SKTO', 'SKTO – Cash Discount (Statistical)'),
        ('VPRS', 'VPRS – Cost (Statistical)'),
        ('PMIN', 'PMIN – Minimum Price (Statistical)'),
        ('ZXXX', 'ZXXX – Custom Condition'),
    ], string='Condition Type')

    line_type = fields.Selection([
        ('condition', 'Condition'),
        ('subtotal', 'Subtotal'),
        ('tax', 'Tax'),
        ('statistical', 'Statistical'),
    ], string='Line Type', required=True, default='condition')

    rule_type = fields.Selection([
        ('discount', 'Discount (-)'),
        ('surcharge', 'Surcharge / Margin (+)'),
        ('charge', 'Additional Charge (+)'),
        ('base_price', 'Base Price (sets price)'),
    ], string='Rule Type', default='discount')

    calculation_type = fields.Selection([
        ('percentage', 'Percentage (%)'),
        ('fixed', 'Fixed Amount'),
    ], string='Calc. Type', required=True, default='percentage')

    account_id = fields.Many2one('account.account', string='GL Account', check_company=True)
    account_key = fields.Char(string='Account Key')
    value = fields.Float(string='Value', default=0.0)
    from_step = fields.Integer(string='From', default=0)
    to_step = fields.Integer(string='To', default=0)
    is_mandatory = fields.Boolean(string='Mandatory', default=False)
    is_statistical = fields.Boolean(string='Statistical', compute='_compute_is_statistical', store=True)
    tax_id = fields.Many2one('account.tax', string='Odoo Tax', domain=[('type_tax_use', '=', 'sale')])
    min_quantity = fields.Float(string='Min Qty', default=0.0)
    max_quantity = fields.Float(string='Max Qty', default=0.0)
    display_value = fields.Char(string='Rate', compute='_compute_display_value')

    tax_base_source = fields.Selection([
        ('mrp', 'MRP (Tax on MRP)'),
        ('running_price', 'Running Net Price'),
    ], string='Tax Base Source', default='mrp',
        help='For tax-type rules only: choose whether to compute tax on MRP '
             '(SAP standard for output tax/MWST) or on the running net price '
             '(e.g. income tax / withholding tax calculated on net sale value).'
    )

    # ── Computed fields ───────────────────────────────────────────────────────

    @api.depends('line_type')
    def _compute_is_statistical(self):
        for rule in self:
            rule.is_statistical = rule.line_type == 'statistical'

    @api.depends('value', 'calculation_type', 'line_type', 'company_id', 'tax_id')
    def _compute_display_value(self):
        for rule in self:
            if rule.line_type == 'subtotal':
                rule.display_value = '—'
            elif rule.line_type == 'tax':
                rule.display_value = rule.tax_id.name if rule.tax_id else 'Tax'
            elif rule.calculation_type == 'percentage':
                rule.display_value = f"{rule.value:.4g}%"
            else:
                symbol = rule.company_id.currency_id.symbol or ''
                rule.display_value = f"{symbol}{rule.value:,.2f}"

    # ── Access control helpers ────────────────────────────────────────────────

    def _is_user_only(self):
        """Return True if current user is a pricing user but NOT an admin."""
        return (
            self.env.user.has_group('sap_pricing_schema.group_sap_pricing_user')
            and not self.env.user.has_group('sap_pricing_schema.group_sap_pricing_admin')
        )

    # ── ORM overrides ─────────────────────────────────────────────────────────

    def write(self, vals):
        if self._is_user_only() and not self.env.context.get('pricing_schema_init'):
            vals = {k: v for k, v in vals.items() if k not in self._ADMIN_ONLY_FIELDS}
            if not vals:
                return True
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):

        return super().create(vals_list)

    def unlink(self):
        """Non-admin users cannot delete pricing rule rows."""
        if self._is_user_only():
            raise UserError(_(
                'Only SAP Pricing Administrators can delete pricing steps.'
            ))
        return super().unlink()

    # ── Business logic ────────────────────────────────────────────────────────

    def apply_rule(self, current_price, quantity=1.0, step_values=None, step_amounts=None):
        self.ensure_one()
        step_values = step_values or {}
        step_amounts = step_amounts or {}

        if self.min_quantity > 0 and quantity < self.min_quantity:
            return {'amount': 0.0, 'new_price': current_price, 'tax_ids': [], 'tax_amount': 0.0, 'tax_base': 0.0}

        base = self._resolve_base(current_price, step_values, step_amounts)

        if self.line_type in ('statistical', 'subtotal') or self.is_statistical:
            return {'amount': base, 'new_price': current_price, 'tax_ids': [], 'tax_amount': 0.0, 'tax_base': 0.0}

        if self.line_type == 'tax':
            tax_amount = 0.0
            tax_ids = []
            if self.tax_id:
                tax_results = self.tax_id.compute_all(base, currency=self.company_id.currency_id, quantity=quantity)
                tax_amount = sum(t.get('amount', 0.0) for t in tax_results.get('taxes', []))
                tax_ids = [self.tax_id.id]
            elif self.value > 0:
                tax_amount = base * (self.value / 100.0)
            return {'amount': tax_amount, 'new_price': current_price, 'tax_ids': tax_ids, 'tax_amount': tax_amount,
                    'tax_base': base}

        if self.rule_type == 'base_price':
            if self.calculation_type == 'fixed' and self.value > 1.0:
                new_price = self.value
            else:
                new_price = current_price
            return {'amount': new_price, 'new_price': new_price, 'tax_ids': [], 'tax_amount': 0.0, 'tax_base': 0.0}

        amount = base * (self.value / 100.0) if self.calculation_type == 'percentage' else self.value
        if self.rule_type == 'discount':
            new_price = max(0.0, current_price - amount)
            amount = current_price if new_price == 0.0 and amount > current_price else amount
        else:
            new_price = current_price + amount

        return {'amount': amount, 'new_price': new_price, 'tax_ids': [], 'tax_amount': 0.0, 'tax_base': base}

    def _resolve_base(self, current_price, step_values, step_amounts=None):
        step_amounts = step_amounts or {}
        if self.from_step > 0 and self.to_step > 0:
            return sum(step_amounts.get(s, 0.0) for s in range(self.from_step, self.to_step + 1))
        if self.from_step > 0:
            return step_values.get(self.from_step, current_price)
        return current_price

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('step', 'from_step', 'to_step')
    def _check_step_sequence(self):
        for record in self:
            if record.from_step >= record.step or record.to_step >= record.step:
                raise ValidationError(_("Reference steps (From/To) must be lower than the current step number."))

    @api.onchange('condition_type', 'rule_type', 'line_type')
    def _onchange_auto_gl_account(self):
        if not self.condition_type:
            return
        domain = [('company_id', '=', self.company_id.id or self.env.company.id),
                  ('condition_type', '=', self.condition_type), ('active', '=', True)]
        if self.line_type != 'tax':
            domain.append(('rule_type', '=', self.rule_type))
        mapping = self.env['pricing.gl.mapping'].search(domain, limit=1)
        if mapping:
            self.account_id, self.account_key = mapping.account_id, mapping.account_key