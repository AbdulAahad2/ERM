from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    # New tolerance field (percentage, optional)
    tolerance_percent = fields.Float(
        string="Tolerance (%)",
        help="Maximum percentage above ordered quantity allowed for receipt. Leave empty for no tolerance."
    )

    @api.constrains('qty_received', 'product_qty', 'tolerance_percent')
    def _check_received_tolerance(self):
        for line in self:
            # Only enforce tolerance if it's set
            if line.tolerance_percent:
                max_qty = line.product_qty * (1 + line.tolerance_percent / 100)
                if line.qty_received > max_qty:
                    raise UserError(_(
                        "Received quantity ({received:.2f}) exceeds the allowed {tolerance:.2f}% tolerance ({max_allowed:.2f}) for product {product}."
                    ).format(
                        received=line.qty_received,
                        tolerance=line.tolerance_percent,
                        max_allowed=max_qty,
                        product=line.product_id.display_name
                    ))
