import logging
from odoo import api, fields, models
_logger = logging.getLogger(__name__)
class VetAnimalVisitLine(models.Model):
    _name = "vet.animal.visit.line"
    _description = "Animal Visit Line"
    # ------------------------------------------------------------------
    #  Existing fields (keep them)
    # ------------------------------------------------------------------
    service_id = fields.Many2one('vet.service', string='Service')
    product_id = fields.Many2one('product.product',
                                 related='service_id.product_id',
                                 store=True, readonly=True)
    service_type = fields.Selection(related='service_id.service_type',
                                    store=True, readonly=True)
    discount = fields.Float("Old Discount % (ignored)", default=0.0)
    visit_id = fields.Many2one('vet.animal.visit', string="Visit")
    quantity = fields.Float('Quantity', default=1.0)
    # ------------------------------------------------------------------
    #  LINE-LEVEL DISCOUNT (the only thing that changes the line)
    # ------------------------------------------------------------------
    line_discount = fields.Float(
        string="Discount % (line)",
        digits=(5, 2),
        default=0.0,
        help="Discount that only applies to this line."
    )
    # ------------------------------------------------------------------
    #  ADD THIS NEW FIELD HERE ✅
    # ------------------------------------------------------------------
    original_price = fields.Float(
        string='Original Price',
        compute='_compute_original_price',
        store=True,
        digits='Product Price',
        help="Original list price before line discount"
    )
    # ------------------------------------------------------------------
    #  PRICE = list_price * (1 - line_discount/100)
    # ------------------------------------------------------------------
    price_unit = fields.Float(
        string='Unit Price',
        compute='_compute_price_unit',
        store=True,
        readonly=False,
        digits='Product Price'
    )
    # ------------------------------------------------------------------
    #  SUBTOTAL = quantity * price_unit
    # ------------------------------------------------------------------
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        store=True,
        digits='Product Price'
    )
    # ------------------------------------------------------------------
    #  Keep the rest of the original fields (invoiced, delivered …)
    # ------------------------------------------------------------------
    invoiced = fields.Boolean(default=False, string="Invoiced")
    delivered = fields.Boolean(default=False, string="Delivered")
    # ------------------------------------------------------------------
    #  ADD THIS NEW COMPUTE METHOD HERE ✅
    # ------------------------------------------------------------------
    @api.depends('service_id', 'service_id.product_id.lst_price')
    def _compute_original_price(self):
        for line in self:
            if line.service_id and line.service_id.product_id:
                line.original_price = line.service_id.product_id.lst_price
            else:
                line.original_price = 0.0
    # ------------------------------------------------------------------
    #  COMPUTED PRICE (list price → line discount)
    # ------------------------------------------------------------------
    @api.depends('service_id', 'service_id.product_id.lst_price',
                 'line_discount', 'quantity')
    def _compute_price_unit(self):
        for line in self:
            if not line.service_id or not line.service_id.product_id:
                line.price_unit = 0.0
                continue
            list_price = line.service_id.product_id.lst_price
            disc = line.line_discount or 0.0
            line.price_unit = list_price * (1 - disc / 100)
    # ------------------------------------------------------------------
    #  SUBTOTAL
    # ------------------------------------------------------------------
    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
            for line in self:
                    line.subtotal = line.quantity * line.price_unit