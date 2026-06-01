from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class PricingGLMapping(models.Model):
    """
    Centralized GL Account Mapping for Pricing Condition Types.

    Configure once per company: which GL account each condition type hits.
    This eliminates the need to set GL accounts repeatedly across schemas.
    """
    _name = 'pricing.gl.mapping'
    _description = 'Pricing GL Account Mapping'
    _order = 'condition_type, rule_type'
    _check_company_auto = True

    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    active = fields.Boolean(default=True)

    # ── Matching Keys ───────────────────────────────────────────────────────
    condition_type = fields.Selection([
        ('PR00', 'PR00 – Base Price'),
        ('K004', 'K004 – Material Discount'),
        ('K005', 'K005 – Customer/Material Discount'),
        ('K007', 'K007 – Customer Discount'),
        ('K020', 'K020 – Price Group Discount'),
        ('HA00', 'HA00 – Order-Value Discount (%)'),
        ('HB00', 'HB00 – Order-Value Discount (Abs)'),
        ('KF00', 'KF00 – Additional Tax'),
        ('HD00', 'HD00 – Delivery Surcharge'),
        ('SUB1', 'Subtotal 1 – Net Value Before Tax'),
        ('SUB2', 'Subtotal 2 – Custom Subtotal'),
        ('MWST', 'MWST – Output Tax'),
        ('JEXT', 'JEXT – External Tax'),
        ('SKTO', 'SKTO – Cash Discount (Statistical)'),
        ('VPRS', 'VPRS – Cost (Statistical)'),
        ('PMIN', 'PMIN – Minimum Price (Statistical)'),
        ('ZXXX', 'ZXXX – Custom Condition'),
    ], string='Condition Type', required=True)

    rule_type = fields.Selection([
        ('discount', 'Discount (-)'),
        ('surcharge', 'Surcharge / Margin (+)'),
        ('charge', 'Additional Charge (+)'),
        ('base_price', 'Base Price'),
    ], string='Rule Type', required=True)

    # ── GL Account ──────────────────────────────────────────────────────────
    # FIXED: account.account uses company_ids (Many2many) in Odoo 18, not company_id
    account_id = fields.Many2one(
        'account.account',
        string='GL Account',
        required=True,
        check_company=True,
        domain="[ '|', ('company_ids', 'in', [company_id]), ('company_ids', '=', False), ('deprecated', '=', False) ]",
        help='The GL account where this condition type will be posted on invoices.'
    )

    account_key = fields.Char(
        string='Account Key',
        help='SAP Account Key (e.g., ERL for Revenue, ERS for Sales Deductions)'
    )

    _sql_constraints = [
        ('unique_condition_rule_company',
         'UNIQUE(condition_type, rule_type, company_id)',
         'A GL mapping for this condition type and rule type already exists in this company!')
    ]

    @api.depends('condition_type', 'rule_type', 'account_id')
    def _compute_name(self):
        for mapping in self:
            mapping.name = f"{mapping.condition_type or ''} → {mapping.account_id.display_name or ''}"


class PricingRule(models.Model):
    _inherit = 'pricing.rule'

    # Override to auto-populate from centralized mapping if not manually set
    @api.onchange('condition_type', 'rule_type', 'company_id')
    def _onchange_condition_type(self):
        """Auto-populate GL account from centralized mapping when condition type changes."""
        if self.condition_type and self.rule_type and not self.account_id:
            mapping = self.env['pricing.gl.mapping'].search([
                ('company_id', '=', self.company_id.id or self.env.company.id),
                ('condition_type', '=', self.condition_type),
                ('rule_type', '=', self.rule_type),
                ('active', '=', True),
            ], limit=1)
            if mapping:
                self.account_id = mapping.account_id
                self.account_key = mapping.account_key