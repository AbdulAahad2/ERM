import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import datetime
from odoo.fields import Date as OdooDate
import traceback as tb

_logger = logging.getLogger(__name__)


class PricingSchema(models.Model):
    _name = 'pricing.schema'
    _description = 'Pricing Schema (SAP-style Pricing Procedure)'
    _order = 'sequence, id'

    name = fields.Char(string='Schema Name', required=True, index=True)
    code = fields.Char(string='Schema Code', index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(
        string='Description',
        help='Optional notes about this pricing schema.',
    )

    # ── Template System ──────────────────────────────────────────────────────
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    is_pricing_admin = fields.Boolean(
        string='Is Pricing Admin',
        compute='_compute_is_pricing_admin',
        store=False,
    )
    is_template = fields.Boolean(
        string='Is Template',
        default=False,
        index=True,
        help='If checked, this schema is a reusable template and will not be used directly on orders.'
    )
    template_code = fields.Char(
        string='Template Code',
        index=True,
        help='Unique code used to recall this template when creating new schemas.'
    )
    source_template_id = fields.Many2one(
        'pricing.schema',
        string='Source Template',
        domain=[('is_template', '=', True)],
        help='The template this schema was copied from (or select one to copy rules from).'
    )

    # ── Applicability ─────────────────────────────────────────────────────────
    customer_ids = fields.Many2many(
        'res.partner',
        'pricing_schema_customer_rel',
        'schema_id', 'partner_id',
        string='Applicable Customers',
        help='Customers this schema applies to. Empty = all customers.'
    )
    product_ids = fields.Many2many(
        'product.product',
        'pricing_schema_product_rel',
        'schema_id', 'product_id',
        string='Applicable Products',
    )
    product_tmpl_ids = fields.Many2many(
        'product.template',
        'pricing_schema_product_tmpl_rel',
        'schema_id', 'product_tmpl_id',
        string='Applicable Product Templates',
    )
    category_ids = fields.Many2many(
        'product.category',
        'pricing_schema_category_rel',
        'schema_id', 'category_id',
        string='Applicable Categories',
    )

    priority = fields.Integer(
        string='Priority', default=5,
        help='Higher = matched first when multiple schemas qualify.'
    )
    match_all_products = fields.Boolean(string='Match All Products', default=False)
    match_all_customers = fields.Boolean(string='Match All Customers', default=False)

    # ── Date Validity (Return Scenario support) ───────────────────────────────
    date_from = fields.Date(
        string='Valid From',
        required=True,
        help='First date this schema is effective.\n'
             'Used to pick the historically correct schema for backdated orders '
             'and credit notes (return scenarios).'
    )
    date_to = fields.Date(
        string='Valid To',
        required=True,
        help='Last date this schema is effective.\n'
             'When a credit note (return) references an invoice dated within this '
             'range the correct period schema is selected automatically.'
    )

    rule_ids = fields.One2many(
        'pricing.rule',
        'schema_id',
        string='Procedure Steps',
        copy=True
    )
    rule_count = fields.Integer(compute='_compute_rule_count', string='Steps')

    default_tax_ids = fields.Many2many(
        'account.tax',
        'pricing_schema_tax_rel',
        'schema_id', 'tax_id',
        string='Default Taxes',
        domain=[('type_tax_use', '=', 'sale')],
        help='Fallback taxes applied when no Tax step is defined in the procedure.'
    )

    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Schema code must be unique!'),
        ('unique_template_code', 'unique(template_code, is_template)', 'Template code must be unique among templates!'),
    ]

    # ── Overlap detection ─────────────────────────────────────────────────────

    def _find_overlapping_schema(self, exclude_id):
        """
        Return the first active non-template schema that conflicts with self,
        or an empty recordset.

        ALWAYS pass exclude_id=self.id (the caller's responsibility).
        exclude_id=None means "don't exclude anything" — only used by the
        onchange for brand-new unsaved records.

        Two schemas conflict when ALL three hold:
          • Date ranges intersect: self.date_from <= other.date_to
                               AND self.date_to   >= other.date_from
          • Customer overlap:  shared customer(s), or either uses match_all
          • Product overlap:   shared product(s),  or either uses match_all
        """
        self.ensure_one()

        # Skip check for templates or records without both dates
        if self.is_template or not (self.date_from and self.date_to):
            return self.env['pricing.schema']

        domain = [
            ('is_template', '=', False),
            ('active', '=', True),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))

        candidates = self.search(domain)
        _logger.debug(
            'pricing.schema._find_overlapping_schema: self=%s (id=%s), '
            'exclude_id=%s, candidates=%s',
            self.name, self.id, exclude_id, candidates.ids
        )

        schema_customer_ids = set(self.customer_ids.ids)
        schema_product_ids = set(self.product_ids.ids)

        for other in candidates:
            # ── Customer overlap? ────────────────────────────────────────────
            if not self.match_all_customers and not other.match_all_customers:
                if not (schema_customer_ids & set(other.customer_ids.ids)):
                    continue

            # ── Product overlap? ─────────────────────────────────────────────
            if not self.match_all_products and not other.match_all_products:
                if not (schema_product_ids & set(other.product_ids.ids)):
                    continue

            _logger.debug(
                'pricing.schema._find_overlapping_schema: CONFLICT '
                'self=%s vs other=%s', self.name, other.name
            )
            return other

        return self.env['pricing.schema']

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('customer_ids', 'match_all_customers')
    def _check_customer_consistency(self):
        for schema in self:
            if schema.match_all_customers and schema.customer_ids:
                raise ValidationError(
                    _('Cannot specify customers when "Match All Customers" is enabled.'))

    @api.constrains('product_ids', 'product_tmpl_ids', 'category_ids', 'match_all_products')
    def _check_product_consistency(self):
        for schema in self:
            if schema.match_all_products and (
                    schema.product_ids or schema.product_tmpl_ids or schema.category_ids):
                raise ValidationError(
                    _('Cannot specify products/categories when "Match All Products" is enabled.'))

    @api.constrains('is_template', 'template_code')
    def _check_template_code_required(self):
        for schema in self:
            if schema.is_template and not schema.template_code:
                raise ValidationError(_('Templates must have a Template Code.'))

    @api.constrains('date_from', 'date_to', 'customer_ids', 'product_ids',
                    'match_all_customers', 'match_all_products')
    def _check_date_overlap(self):
        """
        Hard server-side block — fires on every create AND write.

        Rule 1 — Basic sanity: date_from must be strictly before date_to.
        Rule 2 — No overlap:   two schemas sharing a customer+product pair
                               must not have intersecting validity ranges.
        """
        for schema in self:
            _logger.debug(
                'pricing.schema._check_date_overlap: checking schema=%s '
                'id=%s date_from=%s date_to=%s customers=%s products=%s',
                schema.name, schema.id,
                schema.date_from, schema.date_to,
                schema.customer_ids.ids, schema.product_ids.ids,
            )

            # ── Rule 1 ──────────────────────────────────────────────────────
            if schema.date_from and schema.date_to:
                if schema.date_from == schema.date_to:
                    raise ValidationError(
                        _('Valid From and Valid To must be different dates '
                          'on schema "%s".') % schema.name)
                if schema.date_from > schema.date_to:
                    raise ValidationError(
                        _('Valid From must be earlier than Valid To '
                          'on schema "%s".') % schema.name)

            if schema.is_template or not (schema.date_from and schema.date_to):
                continue

            # ── Rule 2 ──────────────────────────────────────────────────────
            # schema.id is always set here: Odoo inserts the row BEFORE
            # running @api.constrains, so self.id is a real DB id.
            conflict = schema._find_overlapping_schema(exclude_id=schema.id)
            if conflict:
                raise ValidationError(_(
                    'Cannot save "%(schema)s" (%(s_from)s → %(s_to)s).\n\n'
                    'It overlaps with "%(other)s" (%(o_from)s → %(o_to)s) '
                    'for the same customer(s) and product(s).\n\n'
                    'Two schemas sharing a customer and a product must not '
                    'have overlapping validity date ranges.',
                    schema=schema.name,
                    s_from=schema.date_from,
                    s_to=schema.date_to,
                    other=conflict.name,
                    o_from=conflict.date_from,
                    o_to=conflict.date_to,
                ))

    # ── Live onchange warning ─────────────────────────────────────────────────

    @api.onchange('date_from', 'date_to', 'customer_ids', 'product_ids',
                  'match_all_customers', 'match_all_products')
    def _onchange_check_date_overlap(self):
        """
        Popup warning before Save so users see the conflict immediately.
        The hard block in _check_date_overlap is still the authoritative gate.
        """
        # For existing records, exclude self; for new records exclude nothing
        exclude_id = self._origin.id or None
        conflict = self._find_overlapping_schema(exclude_id=exclude_id)
        if conflict:
            return {
                'warning': {
                    'title': _('Date Overlap Detected'),
                    'message': _(
                        '"%(other)s" already covers %(o_from)s → %(o_to)s '
                        'for the same customer(s) and product(s).\n\n'
                        'Saving will be blocked. Please choose non-overlapping dates.',
                        other=conflict.name,
                        o_from=conflict.date_from,
                        o_to=conflict.date_to,
                    ),
                }
            }

    # ── Computed fields ───────────────────────────────────────────────────────

    def _get_customer_taxes(self):
        self.ensure_one()
        for partner in self.customer_ids:
            sales_rate = partner.sap_sales_tax_rate or 0.0
            additional_rate = partner.sap_additional_tax_rate or 0.0
            freight_rate = partner.sap_freight_tax_rate or 0.0
            if sales_rate or additional_rate or freight_rate:
                return sales_rate, additional_rate, freight_rate
        return 0.0, 0.0, 0.0

    def _apply_customer_taxes_to_rules(self, customer=None):
        pass

    def action_sync_taxes_from_customer(self):
        for schema in self:
            schema._apply_customer_taxes_to_rules()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Taxes Synced'),
                'message': _(
                    'MWST (Sales Tax), JEXT (Income Tax), and KF00 (Additional Tax) rules updated from customer tax settings.'),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.onchange('customer_ids', 'match_all_customers')
    def _onchange_customer_ids_sync_taxes(self):
        self._apply_customer_taxes_to_rules()

    def write(self, vals):
        # Changed from error to debug to avoid false-positive error flags during upgrades
        _logger.debug(
            "!!DEBUG!! pricing.schema.write ids=%s vals_keys=%s\n%s",
            self.ids, list(vals.keys()), ''.join(tb.format_stack())
        )
        result = super().write(vals)
        if 'customer_ids' in vals or 'match_all_customers' in vals:
            for schema in self:
                schema._apply_customer_taxes_to_rules()
        return result

    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for schema in self:
            schema.rule_count = len(schema.rule_ids)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_rule_name(rule):
        return rule.name or f"Step {rule.step}"

    # ── Template System Core ─────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.user.has_group('sap_pricing_schema.group_sap_pricing_admin')
        is_user_only = self.env.user.has_group('sap_pricing_schema.group_sap_pricing_user') and not is_admin

        # 1. Prepare values based on security roles
        if is_user_only:
            # Strip 'rule_ids' out of the creation vals for non-admin users
            clean_vals = [{k: v for k, v in vals.items() if k != 'rule_ids'} for vals in vals_list]
            records = super().create(clean_vals)
        else:
            records = super().create(vals_list)

        # 2. Single loop for post-creation logic (Batch-friendly where possible)
        for record in records:

            if is_user_only and record.source_template_id:
                record.with_context(pricing_schema_init=True).action_copy_from_template()

            # Apply customer taxes if customers are defined
            if record.customer_ids:
                record._apply_customer_taxes_to_rules()

        return records

    def _copy_template_rules(self):
        return [(0, 0, {
            'name': self._safe_rule_name(rule),
            'step': rule.step,
            'counter': rule.counter,
            'condition_type': rule.condition_type,
            'line_type': rule.line_type,
            'rule_type': rule.rule_type,
            'calculation_type': rule.calculation_type,
            'value': rule.value,
            'from_step': rule.from_step,
            'to_step': rule.to_step,
            'is_mandatory': rule.is_mandatory,
            'is_statistical': rule.is_statistical,
            'tax_id': rule.tax_id.id if rule.tax_id else False,
            'account_id': rule.account_id.id if rule.account_id else False,
            'account_key': rule.account_key,
            'min_quantity': rule.min_quantity,
            'max_quantity': rule.max_quantity,
            'active': rule.active,
        }) for rule in self.rule_ids]

    @api.onchange('code')
    def _onchange_code_load_template(self):
        if self.code and not self.rule_ids and not self.is_template:
            template = self.search([
                ('is_template', '=', True),
                ('template_code', '=', self.code),
                ('active', '=', True)
            ], limit=1)
            if template:
                self.name = template.name
                self.description = template.description
                self.sequence = template.sequence
                self.priority = template.priority
                self.match_all_customers = template.match_all_customers
                self.match_all_products = template.match_all_products
                self.default_tax_ids = template.default_tax_ids
                self.source_template_id = template.id
                self.rule_ids = template._copy_template_rules()

    @api.onchange('source_template_id')
    def _onchange_source_template_load_rules(self):
        if self.source_template_id and not self.rule_ids:
            template = self.source_template_id
            self.rule_ids = template._copy_template_rules()

    def _compute_is_pricing_admin(self):
        is_admin = self.env.user.has_group('sap_pricing_schema.group_sap_pricing_admin')
        for record in self:
            record.is_pricing_admin = is_admin

    def action_copy_from_template(self):
        self.ensure_one()
        if not self.source_template_id:
            return
        rule_model = self.env['pricing.rule'].with_context(pricing_schema_init=True)
        for rule in self.source_template_id.rule_ids:
            rule_model.create({
                'schema_id': self.id,
                'name': rule.name,
                'step': rule.step,
                'counter': rule.counter,
                'condition_type': rule.condition_type,
                'line_type': rule.line_type,
                'rule_type': rule.rule_type,
                'calculation_type': rule.calculation_type,
                'from_step': rule.from_step,
                'to_step': rule.to_step,
                'value': rule.value,
                'is_mandatory': rule.is_mandatory,
                'tax_id': rule.tax_id.id if rule.tax_id else False,
                'account_id': rule.account_id.id if rule.account_id else False,
                'account_key': rule.account_key,
                'tax_base_source': rule.tax_base_source,
            })

    def action_save_as_template(self):
        self.ensure_one()
        if self.is_template:
            raise ValidationError(_('This schema is already a template.'))
        if not self.code:
            raise ValidationError(_('Please set a Schema Code before saving as template.'))
        template_vals = {
            'name': f"{self.name} (Template)",
            'code': f"TPL_{self.code}",
            'template_code': self.code,
            'is_template': True,
            'active': True,
            'sequence': self.sequence,
            'priority': self.priority,
            'match_all_customers': self.match_all_customers,
            'match_all_products': self.match_all_products,
            'default_tax_ids': [(6, 0, self.default_tax_ids.ids)],
            'description': self.description,
            'date_from': self.date_from,  # ← ADD
            'date_to': self.date_to,  # ← ADD
            'rule_ids': self._copy_template_rules(),
        }
        template = self.create(template_vals)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pricing.schema',
            'view_mode': 'form',
            'res_id': template.id,
            'target': 'current',
        }

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default['is_template'] = False
        default['template_code'] = False
        default['source_template_id'] = False
        return super().copy(default)

    # ── Schema Matching ───────────────────────────────────────────────────────

    @api.model
    def get_matching_schema(self, partner_id, product_id, template_code=None, order_date=None, header_only=False):

        def _to_date(val):
            if not val:
                return None
            if isinstance(val, datetime.datetime):
                return val.date()
            if isinstance(val, datetime.date):
                return val
            if isinstance(val, str):
                try:
                    return datetime.date.fromisoformat(val[:10])
                except ValueError:
                    return None
            return None

        check_date = _to_date(order_date) or OdooDate.today()
        base_domain = [('active', '=', True), ('is_template', '=', False)]
        schemas = self.search(base_domain, order='priority desc, sequence, id')

        def _date_valid(schema):
            d_from = _to_date(schema.date_from)
            d_to = _to_date(schema.date_to)
            if d_from and check_date < d_from:
                return False
            if d_to and check_date > d_to:
                return False
            return True

        def _has_product_filter(schema):
            return bool(schema.product_ids or schema.product_tmpl_ids or schema.category_ids)

        def _partner_and_date_ok(schema):
            return _date_valid(schema) and schema._matches_partner(partner_id)

        # ── NEW: nearest-schema picker ────────────────────────────────────────
        # For a date outside all ranges, pick the schema whose range endpoint
        # is closest to check_date. Past schemas (already ended) are preferred
        # over future schemas (not yet started) when equidistant.
        def _nearest_schema(candidates):
            """
            Return the nearest schema by distance from check_date to its range.
            - date inside range  → distance 0  (exact match, already handled above)
            - date after range   → distance = days since date_to  (past schema)
            - date before range  → distance = days until date_from (future schema)
            Tiebreak: prefer past over future, then most-recently-ended, then priority.
            """
            if not candidates:
                return False

            def _dist(s):
                d_from = _to_date(s.date_from) or datetime.date.min
                d_to = _to_date(s.date_to) or datetime.date.max
                if check_date > d_to:
                    return (check_date - d_to).days  # past schema
                elif check_date < d_from:
                    return (d_from - check_date).days  # future schema
                return 0  # exact (shouldn't reach here)

            def _sort_key(s):
                d_to = _to_date(s.date_to) or datetime.date.min
                # 0 = past schema (preferred), 1 = future schema
                is_future = 1 if check_date < (_to_date(s.date_from) or datetime.date.min) else 0
                return (
                    _dist(s),  # closest first
                    is_future,  # past preferred over future
                    -d_to.toordinal(),  # most recently ended first
                    -s.priority,
                    s.sequence,
                )

            return min(candidates, key=_sort_key)

        # ─────────────────────────────────────────────────────────────────────

        if header_only or not product_id:
            if template_code:
                code_schemas = schemas.filtered(lambda s: s.code == template_code)
                for schema in code_schemas:
                    if _partner_and_date_ok(schema):
                        return schema

            # Exact date match first — catch-all schemas only (no product filter)
            valid = [s for s in schemas if _partner_and_date_ok(s) and not _has_product_filter(s)]
            if valid:
                return valid[0]

            # Nearest fallback — still catch-all only
            catch_all = [
                s for s in schemas
                if s._matches_partner(partner_id) and not _has_product_filter(s)
            ]
            return _nearest_schema(catch_all)

        # ── Line-level lookup (product_id is known) ───────────────────────────
        if template_code:
            code_schemas = schemas.filtered(lambda s: s.code == template_code)
            for schema in code_schemas:
                if _partner_and_date_ok(schema) and schema._matches_product(product_id):
                    return schema
            for schema in code_schemas:
                if _partner_and_date_ok(schema) and schema.match_all_products:
                    return schema
            # Nearest within template-code schemas
            code_candidates = [
                s for s in code_schemas
                if s._matches_partner(partner_id) and s._matches_product(product_id)
            ]
            nearest = _nearest_schema(code_candidates)
            if nearest:
                return nearest

        # Exact date match
        for schema in schemas:
            if _partner_and_date_ok(schema) and schema._matches_product(product_id):
                return schema

        # Nearest fallback — must still match customer AND product
        candidates = [
            s for s in schemas
            if s._matches_partner(partner_id) and s._matches_product(product_id)
        ]
        return _nearest_schema(candidates)

    def _matches_partner(self, partner_id):
        self.ensure_one()
        if self.match_all_customers or not self.customer_ids:
            return True
        return partner_id in self.customer_ids.ids

    def _matches_product(self, product_id):
        self.ensure_one()
        if self.match_all_products:
            return True
        if not (self.product_ids or self.product_tmpl_ids or self.category_ids):
            return True
        if not product_id:
            return False
        product = self.env['product.product'].browse(product_id)
        if self.product_ids and product_id in self.product_ids.ids:
            return True
        if self.product_tmpl_ids and product.product_tmpl_id.id in self.product_tmpl_ids.ids:
            return True
        if self.category_ids and product.categ_id.id in self.category_ids.ids:
            return True
        return False

    # ── Pricing Procedure Engine ──────────────────────────────────────────────

    def apply_pricing(self, mrp_price, quantity=1.0, partner=None):
        self.ensure_one()

        step_values = {}
        step_amounts = {}

        result = {
            'mrp_price': mrp_price,
            'final_price': mrp_price,
            'final_amount': mrp_price * quantity,
            'discount_amount': 0.0,
            'surcharge_amount': 0.0,
            'charge_amount': 0.0,
            'tax_amount': 0.0,
            'subtotals': {},
            'tax_ids': [],
            'steps': [],
        }

        current_price = mrp_price
        active_rules = self.rule_ids.filtered(lambda r: r.active).sorted(
            key=lambda r: (r.step, r.counter)
        )

        for rule in active_rules:
            override_value = None
            if partner:
                if rule.condition_type == 'MWST':
                    override_value = partner.sap_sales_tax_rate
                elif rule.condition_type == 'JEXT':
                    override_value = partner.sap_additional_tax_rate
                elif rule.condition_type == 'KF00':
                    override_value = partner.sap_freight_tax_rate

            rule_result = rule.apply_rule(
                current_price,
                quantity=quantity,
                step_values=step_values,
                override_value=override_value,
            )

            amount = rule_result['amount']
            new_price = rule_result['new_price']
            tax_ids = rule_result.get('tax_ids', [])
            tax_amount = rule_result.get('tax_amount', 0.0)

            for tid in tax_ids:
                if tid not in result['tax_ids']:
                    result['tax_ids'].append(tid)

            if tax_amount:
                result['tax_amount'] += tax_amount

            if not rule.is_statistical and rule.line_type == 'condition':
                if rule.rule_type == 'discount':
                    result['discount_amount'] += amount
                elif rule.rule_type == 'surcharge':
                    result['surcharge_amount'] += amount
                elif rule.rule_type == 'charge':
                    result['charge_amount'] += amount

            if rule.line_type == 'subtotal':
                result['subtotals'][rule.step] = new_price

            step_values[rule.step] = new_price
            step_amounts[rule.step] = amount

            result['steps'].append({
                'step': rule.step,
                'counter': rule.counter,
                'condition_type': rule.condition_type or '—',
                'name': rule.name,
                'line_type': rule.line_type,
                'rule_type': rule.rule_type,
                'calc_type': rule.calculation_type,
                'value': override_value if override_value is not None else rule.value,
                'from_step': rule.from_step,
                'to_step': rule.to_step,
                'is_statistical': rule.is_statistical,
                'is_mandatory': rule.is_mandatory,
                'amount': amount,
                'running_price': new_price,
                'tax_ids': tax_ids,
                'tax_amount': tax_amount,
                'display_value': rule.display_value,
            })

            if not rule.is_statistical and rule.line_type != 'tax':
                current_price = new_price

        result['final_price'] = current_price
        result['final_amount'] = current_price * quantity
        return result

    def action_load_standard_template(self):
        self.ensure_one()
        if self.rule_ids:
            raise ValidationError(
                _('This schema already has steps. Clear them first if you want to reload the template.'))

        default_tax = self.env['account.tax'].search(
            [('type_tax_use', '=', 'sale'), ('company_id', '=', self.env.company.id)],
            limit=1
        )

        template_steps = [
            (10, 0, 'PR00', 'Base Price (MRP)', 'condition', 'base_price', 'fixed', 0.0, 0, 0, True),
            (20, 0, 'K007', 'Customer Discount', 'condition', 'discount', 'percentage', 0.0, 10, 10, False),
            (30, 0, 'K004', 'Material Discount', 'condition', 'discount', 'percentage', 0.0, 10, 10, False),
            (40, 0, 'HA00', 'Order-Value Discount (%)', 'condition', 'discount', 'percentage', 0.0, 10, 10, False),
            (50, 0, 'HB00', 'Order-Value Discount (Abs)', 'condition', 'discount', 'fixed', 0.0, 10, 10, False),
            (100, 0, 'SKTO', 'Cash Discount (Statistical)', 'statistical', 'discount', 'percentage', 2.0, 0, 0, False),
            (200, 0, 'KF00', 'Additional Tax', 'condition', 'charge', 'percentage', 0.0, 10, 300, False),
            (300, 0, 'HD00', 'Handling Surcharge', 'condition', 'surcharge', 'percentage', 0.0, 10, 10, False),
            (700, 0, 'SUB1', 'Net Value (before tax)', 'subtotal', 'discount', 'percentage', 0.0, 10, 300, False),
            (710, 0, 'MWST', 'Output Tax', 'tax', 'discount', 'percentage', 0.0, 700, 700, True),
            (900, 0, 'VPRS', 'Cost / COGS (Statistical)', 'statistical', 'discount', 'fixed', 0.0, 0, 0, False),
        ]

        vals_list = []
        for (step, counter, ctype, desc, ltype, rtype, ctype2, val, frm, to, mandatory) in template_steps:
            v = {
                'schema_id': self.id,
                'step': step,
                'counter': counter,
                'condition_type': ctype,
                'name': desc,
                'line_type': ltype,
                'rule_type': rtype,
                'calculation_type': ctype2,
                'value': val,
                'from_step': frm,
                'to_step': to,
                'is_mandatory': mandatory,
                'active': True,
            }
            if ctype == 'MWST' and default_tax:
                v['tax_id'] = default_tax.id
            vals_list.append(v)

        self.env['pricing.rule'].with_context(pricing_schema_init=True).create(vals_list)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Template Loaded'),
                'message': _('Standard SAP RVAA01-style procedure created. '
                             'Update values (discounts, charges) as needed.'),
                'type': 'success',
                'sticky': False,
            }
        }