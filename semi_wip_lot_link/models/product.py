from odoo import models, fields, api
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_semi_wip = fields.Boolean(
        compute="_compute_is_semi_wip",
        store=False
    )

    lot_initial = fields.Char(
        string="Lot Initial",
        help="Initial used in lot number for semi-finished products (e.g. INITIAL, ST)"
    )

    @api.depends("default_code")
    def _compute_is_semi_wip(self):
        for product in self:
            product.is_semi_wip = bool(
                product.default_code
                and "initial-wip" in product.default_code.lower()
            )

    @api.constrains("is_semi_wip", "lot_initial")
    def _check_lot_initial(self):
        for product in self:
            if product.is_semi_wip and not product.lot_initial:
                raise UserError(
                    "Semi-finished product requires a Lot Initial."
                )
