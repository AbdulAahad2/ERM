# -*- coding: utf-8 -*-
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_repr


class PosSaleCommission(models.Model):
    _name = 'pos.sale.commission'
    _description = "Commission"

    def _get_default_currency_id(self):
        return self.env.company.currency_id.id

    currency_id = fields.Many2one('res.currency', string='Currency', default=_get_default_currency_id, required=True)
    name = fields.Char(string='Name', required=True)
    active = fields.Boolean('Active', default=True)
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    commission_line_ids = fields.One2many('pos.sale.commission.line', 'commission_id', 'Commission Lines')
    commission_rule = fields.Selection([
            ('amount', 'Total Amount'),
            ('rule', 'Products'),
            ], string='Rule', required=True,default='rule')
    cart_amount_commission_ids = fields.One2many('cart.amount.rule', 'pos_commission_id', string='Cart Amount Rules')

    @api.constrains('start_date', 'end_date', 'commission_rule', 'cart_amount_commission_ids')
    def check_dates(self):
        if(self.start_date and self.end_date):
            if(self.end_date < self.end_date):
                raise ValidationError('Start Date Cannot be smaller than End Date')

        if(self.commission_rule == 'amount'):
            if(len(self.cart_amount_commission_ids) > 1):
                for line1 in self.cart_amount_commission_ids:
                    for line2 in self.cart_amount_commission_ids:
                        if(line1.id != line2.id):
                            flag = 0
                            if(line2.cart_amount_from < line1.cart_amount_from and line2.cart_amount_from < line1.cart_amount_to and line2.cart_amount_to < line1.cart_amount_to and line2.cart_amount_to < line1.cart_amount_from):
                                flag+=1
                            elif(line2.cart_amount_from > line1.cart_amount_from and line2.cart_amount_from > line1.cart_amount_to and line2.cart_amount_to > line1.cart_amount_to and line2.cart_amount_to > line1.cart_amount_from):
                                flag+=1
                            
                            if(not flag):
                                raise ValidationError('There is some overlapping in the Rule. Please Check and re-assign the Rules.')

    def compute_commission(self, product, price_unit, qty,commission_id):
        if(product and price_unit and qty and commission_id):
            commission = self.search([('id', '=', commission_id)])
            product = self.env['product.product'].search([('id', '=', product)])

            if(commission and commission.active):
                is_commission_applicable = True
                if(commission.start_date and commission.end_date):
                    current_date = date.today()
                    if(current_date >= commission.start_date and current_date <= commission.end_date):
                        is_commission_applicable = True
                    else:
                        is_commission_applicable = False

                if (is_commission_applicable):
                    apply_commission_line_id = None
                    if(commission.commission_rule == 'rule'):
                        if(commission.commission_line_ids):
                            for line in commission.commission_line_ids:
                                if(line.apply_on == '3_all'):
                                    apply_commission_line_id = line.id
                                elif(line.apply_on == '2_categories'):
                                    if (product.categ_id.parent_id):
                                        parent_path_list = list(map(int, list(value for value in list(product.categ_id.parent_path.split("/")) if value)))
                                        if line.categ_id.id in parent_path_list:
                                            apply_commission_line_id = line.id
                                    else:
                                        if(product.categ_id == line.categ_id):
                                            apply_commission_line_id = line.id
                                elif(line.apply_on == '1_products'):
                                    if(product.id == line.product_id.id):
                                        apply_commission_line_id = line.id
                        
                                if(apply_commission_line_id):
                                    commission_detail = self.env['pos.sale.commission.line'].search([('id', '=', apply_commission_line_id)])
                                    if(commission_detail):
                                        if(qty >= commission_detail.min_qty):
                                            if(commission_detail.compute_commision == 'percentage'):
                                                commission_amount = ((price_unit*qty)*commission_detail.percent_commission)/100 
                                                return commission_amount
                                            else:
                                                commission_amount = (int(qty)*commission_detail.fixed_commission)
                                                return commission_amount

    def compute_commission_based_on_amount(self, amount_total, commission_id):
        if(amount_total and commission_id):
            commission = self.search([('id', '=', commission_id)])
            if(commission and commission.active and (commission.commission_rule == 'amount')): 
                is_commission_applicable = True
                if(commission.start_date and commission.end_date):
                    current_date = date.today()
                    if(current_date >= commission.start_date and current_date <= commission.end_date):
                        is_commission_applicable = True
                    else:
                        is_commission_applicable = False
                if(is_commission_applicable):      
                    cart_rules = self.env['cart.amount.rule'].search([('pos_commission_id', '=', commission_id)])
                    for rule in cart_rules:
                        if(amount_total >= rule.cart_amount_from and amount_total <= rule.cart_amount_to):
                            if(rule.compute_commision == 'percentage'):
                                commission_amount = (amount_total*rule.percent_commission)/100 
                                return commission_amount
                            else:
                                commission_amount = (rule.fixed_commission)
                                return commission_amount
                    
class CartAmountRuleList(models.Model):
    _name = 'cart.amount.rule'
    _description = "Cart Amount Rule List"
    pos_commission_id = fields.Many2one('pos.sale.commission', string='Commission')
    name = fields.Char(string='Name', size=100, required=True)
    active = fields.Boolean(string="Active", default=True)
    cart_amount_from = fields.Integer(string='Cart Amount from', required=True)
    cart_amount_to = fields.Integer(string='Cart Amount to', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, help="Currency of your Company.", default=lambda self: self.env.user.company_id.currency_id.id)
    compute_commision = fields.Selection([
        ('fixed', 'Fixed'),
        ('percentage', 'Percentage')],
        default='fixed', string='Compute Commission')

    fixed_commission = fields.Monetary('Fixed Commission')
    percent_commission = fields.Float('Percentage Commission')
    commission = fields.Char('Commissions', compute='_get_cart_amount_rule_commission')

    @api.constrains('cart_amount_from', 'cart_amount_to')
    def check_constrains(self):
        for data in self:
            if(data.cart_amount_from > data.cart_amount_to):
                raise ValidationError('Cart Amount from Cannot be greater then Cart Amount to in : ' + data.name)
            if(data.cart_amount_from == data.cart_amount_to):
                raise ValidationError('Cart Amount from Cannot be equal to Cart Amount to in : ' + data.name)

    @api.depends('fixed_commission','percent_commission','commission','currency_id')
    def _get_cart_amount_rule_commission(self):
        for value in self:
            if value.compute_commision == 'fixed':
                if value.currency_id.position == 'after':
                    value.commission = "%s %s" % (
                        float_repr(
                            value.fixed_commission,
                            value.currency_id.decimal_places,
                        ),
                        value.currency_id.symbol,
                    )
                else:
                    value.commission = "%s %s" % (
                        value.currency_id.symbol,
                        float_repr(
                            value.fixed_commission,
                            value.currency_id.decimal_places,
                        ),
                    )
            elif value.compute_commision == 'percentage':
                value.commission = _("%s %%") % (value.percent_commission)

class PosSaleCommissionLine(models.Model):
    _name = 'pos.sale.commission.line'
    _description = 'Commission line'
    _order =  "apply_on, min_qty desc, categ_id desc, id desc"

    def _get_default_currency_id(self):
        return self.env.company.currency_id.id

    sequence = fields.Integer(default=16)
    sequence1 = fields.Integer(string="Sequences") 
    currency_id = fields.Many2one('res.currency', string='Currency', default=_get_default_currency_id, required=True)
    apply_on = fields.Selection([
        ('3_all', 'All Products'),
        ('2_categories', 'Categories'),
        ('1_products', 'Products')],
        default='3_all', string='Apply On')
    min_qty = fields.Integer(string='Min. Quantity', default='0')
    categ_id = fields.Many2one('product.category', 'Product Category')
    product_id = fields.Many2one('product.product', 'Product Variant', domain=[('available_in_pos', '=', True)])
    name = fields.Char(string='Name', compute='_get_commission_line_name')

    compute_commision = fields.Selection([
        ('fixed', 'Fixed'),
        ('percentage', 'Percentage')],
        default='fixed', string='Compute Commission')

    fixed_commission = fields.Monetary('Fixed Commission')
    percent_commission = fields.Float('Percentage Commission')
    commission = fields.Char('Commissions', compute='_get_sale_commission_line_name_commission')

    @api.onchange('sequence')
    def _change_sequence(self):
        for data in self:
            data.sequence1 = data.sequence

    @api.depends('apply_on', 'categ_id', 'product_id', 'compute_commision', 'fixed_commission', 'percent_commission')
    def _get_commission_line_name(self):
        for item in self:
            if item.categ_id and item.apply_on == '2_categories':
                item.name = _("Category: %s") % (item.categ_id.display_name)
            elif item.product_id and item.apply_on == '1_products':
                item.name = _("Variant: %s") % (item.product_id.with_context(display_default_code=False).display_name)
            else:
                item.name = _("All Products")

    @api.depends('fixed_commission','percent_commission','commission','currency_id')
    def _get_sale_commission_line_name_commission(self):
        for value in self:
            if value.compute_commision == 'fixed':
                if value.currency_id.position == 'after':
                    value.commission = "%s %s" % (
                        float_repr(
                            value.fixed_commission,
                            value.currency_id.decimal_places,
                        ),
                        value.currency_id.symbol,
                    )
                else:
                    value.commission = "%s %s" % (
                        value.currency_id.symbol,
                        float_repr(
                            value.fixed_commission,
                            value.currency_id.decimal_places,
                        ),
                    )
            elif value.compute_commision == 'percentage':
                value.commission = _("%s %%") % (value.percent_commission)


    @api.onchange('compute_commision')
    def _onchange_compute_commision(self):
        if self.compute_commision != 'fixed':
            self.fixed_commission = 0.0
        if self.compute_commision != 'percentage':
            self.percent_commission = 0.0

    commission_id =  fields.Many2one('pos.sale.commission', string='Commission')
