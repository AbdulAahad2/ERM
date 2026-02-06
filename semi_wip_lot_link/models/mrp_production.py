from odoo import models, fields
from odoo.exceptions import UserError
from datetime import datetime

class MrpProduction(models.Model):
    _inherit = "mrp.production"

    # Link to semi-finished lot (only relevant for finished products)
    semi_lot_id = fields.Many2one(
        "stock.lot",
        string="Semi Finished Lot"
    )

    def action_confirm(self):
        """Override confirm to generate semi/finished lots automatically."""
        res = super().action_confirm()

        for mo in self:
            tmpl = mo.product_id.product_tmpl_id
            year = datetime.now().strftime("%y")

            # -----------------------
            # SEMI-FINISHED PRODUCT
            # -----------------------
            if tmpl.is_semi_wip:
                # Generate sequence
                seq = self.env["ir.sequence"].next_by_code("semi.wip.lot")
                initial = tmpl.lot_initial.upper()

                # Lot name: INITIAL-WIP-YY-XXXX
                lot_name = f"{initial}-WIP-{year}-{seq}"

                # Create the lot
                lot = self.env["stock.lot"].create({
                    "name": lot_name,
                    "product_id": mo.product_id.id,
                    "company_id": mo.company_id.id,
                    "semi_sequence": seq,
                    "lot_initial": initial,
                })

                # Assign lot to MO
                mo.lot_producing_id = lot

            # -----------------------
            # FINISHED PRODUCT
            # -----------------------
            else:
                # Finished product requires a semi lot
                if not mo.semi_lot_id:
                    raise UserError(
                        "Finished product requires a Semi-Finished Lot."
                    )

                semi_lot = mo.semi_lot_id

                # Lot name: B-INITIAL-YY-XXXX (same sequence as semi)
                lot_name = f"B-{semi_lot.lot_initial}-{year}-{semi_lot.semi_sequence}"

                # Create the finished lot
                lot = self.env["stock.lot"].create({
                    "name": lot_name,
                    "product_id": mo.product_id.id,
                    "company_id": mo.company_id.id,
                    "semi_sequence": semi_lot.semi_sequence,
                    "lot_initial": semi_lot.lot_initial,
                })

                # Assign lot to MO
                mo.lot_producing_id = lot

        return res
