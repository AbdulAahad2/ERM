from odoo import models, api
from odoo.exceptions import UserError

class StockLot(models.Model):
    _inherit = 'stock.lot'

    @api.model
    def create(self, vals):
        # If name is already provided, allow creation
        if vals.get('name'):
            return super().create(vals)

        ctx = self.env.context

        # Only enforce custom logic when coming from MRP
        if ctx.get('from_mrp_production'):
            lot_name = ctx.get('semi_finish_code') or ctx.get('finish_code')

            if not lot_name:
                raise UserError(
                    "Lot/Serial Number must be generated from Manufacturing Order."
                )

            vals['name'] = lot_name

        # All other flows → normal Odoo behavior
        return super().create(vals)
