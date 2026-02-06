from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class EmployeeRequisitionLine(models.Model):
    _name = 'employee.requisition.line'
    _description = 'Employee Requisition Line'

    requisition_id = fields.Many2one('employee.requisition', ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    quantity = fields.Float(default=1.0)
    unit_price = fields.Float(string="Unit Price")
    vendor_id = fields.Many2one('res.partner', string='Vendor')
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True)
    currency_id = fields.Many2one('res.currency', related='requisition_id.currency_id')

    @api.depends('quantity', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_price

    @api.onchange('product_id')
    def _onchange_product_id_set_price_vendor(self):
        """
        Logic: Pull internal cost only.
        Vendor is explicitly set to False to keep it empty.
        """
        for line in self:
            # 1. Reset Vendor to empty
            line.vendor_id = False

            if not line.product_id:
                line.unit_price = 0.0
                continue

            # 2. Pull Price from 'General Information' -> 'Cost' field
            line.unit_price = line.product_id.standard_price

            _logger.info("Onchange: Product %s set to Cost %s. Vendor cleared.",
                         line.product_id.name, line.unit_price)