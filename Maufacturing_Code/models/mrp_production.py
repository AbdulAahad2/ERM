import logging
import re
from datetime import datetime
from odoo import models, api, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    is_semi_finish = fields.Boolean(
        string="Is Semi-Finish",
        default=False,
        help="Check if this MO produces a semi-finished product"
    )
    semi_finish_code = fields.Char(string="Semi-Finish Code", readonly=True)
    finish_code = fields.Char(string="Finish Code", readonly=True)
    dont_autogenerate = fields.Boolean(
        string="Don't Auto-Generate Finished Lot",
        default=False,
        help="If checked, you can pick a semi-finished lot to generate the finished lot from."
    )

    manual_semi_lot_id = fields.Many2one(
        'stock.lot',
        string="Select Semi-Finished Lot",
        domain="[('product_id.product_tmpl_id.is_semi_product', '=', True)]",
        help="Pick a semi-finished lot to generate the finished lot from."
    )

    def action_generate_custom_mfg_lot(self):
        self.ensure_one()

        if not self.product_id or self.product_id.tracking == 'none':
            raise UserError("Product must be tracked by Lots/Serials.")

        StockLot = self.env['stock.lot']
        year = datetime.now().strftime('%y')

        # Determine if this MO is semi-finished
        self.is_semi_finish = bool(self.product_id.product_tmpl_id.is_semi_product)

        # ========================
        # SEMI-FINISHED PRODUCT
        # ========================
        if self.is_semi_finish:
            semi_initial = self.product_id.product_tmpl_id.semi_finish_initial
            if not semi_initial:
                raise UserError("Semi-Finish Initial must be set on the Product Template.")

            prefix = f"{semi_initial}-WIP-{year}"

            # Get last lot for this product
            last_lot = StockLot.search([
                ('product_id', '=', self.product_id.id),
                ('name', '=like', f'{prefix}-%')
            ], order='id desc', limit=1)

            last_number = 0
            if last_lot:
                match = re.search(r'-(\d+)$', last_lot.name)
                if match:
                    last_number = int(match.group(1))

            lot_number = str(last_number + 1).zfill(5)
            lot_name = f"{prefix}-{lot_number}"
            self.semi_finish_code = lot_name

            # Create or fetch lot
            lot = StockLot.search([
                ('name', '=', lot_name),
                ('product_id', '=', self.product_id.id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            if not lot:
                lot = StockLot.create({
                    'name': lot_name,
                    'product_id': self.product_id.id,
                    'company_id': self.company_id.id,
                })

            self.lot_producing_id = lot.id

        # ========================
        # FINISHED PRODUCT
        # ========================
        if not self.is_semi_finish:
            self.ensure_one()

            if not self.product_id or self.product_id.tracking == 'none':
                raise UserError("Product must be tracked by Lots/Serials.")

            StockLot = self.env['stock.lot']
            year = datetime.now().strftime('%y')

            # Get semi initial from FINISHED product template
            semi_initial = self.product_id.product_tmpl_id.semi_finish_initial
            if not semi_initial:
                raise UserError("Semi-Finish Initial must be set on the Finished Product Template.")

            # ------------------------------------------------
            # Get semi-finished lot from raw material lines
            # ------------------------------------------------
            semi_lot = None
            for move in self.move_raw_ids:
                line = move.move_line_ids.filtered(lambda l: l.lot_id)
                if line:
                    semi_lot = line[0].lot_id
                    break

            if not semi_lot:
                raise UserError("Please select a semi-finished lot in the raw material lines.")

            # Extract last digits from semi-finished lot
            match = re.search(r'-(\d+)$', semi_lot.name)
            if not match:
                raise UserError("Invalid Semi-Finished Lot format.")

            lot_number = match.group(1)

            # Finished lot name
            lot_name = f"B-{semi_initial}-{year}-{lot_number}"

            self.finish_code = lot_name
            self.semi_finish_code = semi_lot.name

            # ------------------------------------------------
            # Create or reuse finished lot
            # ------------------------------------------------
            lot = StockLot.search([
                ('name', '=', lot_name),
                ('product_id', '=', self.product_id.id),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            if not lot:
                lot = StockLot.create({
                    'name': lot_name,
                    'product_id': self.product_id.id,
                    'company_id': self.company_id.id,
                })

            self.lot_producing_id = lot.id

            # ------------------------------------------------
            # Assign finished lot to finished move lines
            # ------------------------------------------------
            for move in self.move_finished_ids.filtered(lambda m: m.product_id == self.product_id):
                if not move.move_line_ids:
                    move._generate_serial_numbers()

                for line in move.move_line_ids:
                    line.write({
                        'lot_id': lot.id,
                        'quantity': self.product_qty
                    })

            _logger.info(
                ">>> Finished Lot %s created from Semi Lot %s",
                lot_name,
                semi_lot.name
            )
            return True
