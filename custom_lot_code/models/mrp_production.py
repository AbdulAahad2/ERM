import logging
import re
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_generate_custom_mfg_lot(self):
        """Logic for MO: ProductCode-0001, 0002... and assign to lot_producing_id"""
        self.ensure_one()
        _logger.info(">>> Starting Custom MFG Lot Generation for MO: %s", self.name)

        if not self.product_id or self.product_id.tracking == 'none':
            _logger.warning(">>> MO %s product is not tracked by Lots/Serials.", self.name)
            return

        # 1. Get Prefix from Product
        prefix = self.product_id.manuf_lot_code or "MFG"
        _logger.info(">>> Using Prefix: %s for Product: %s", prefix, self.product_id.display_name)

        # 2. Find the last lot for this product with this prefix
        last_lot = self.env['stock.lot'].search([
            ('product_id', '=', self.product_id.id),
            ('name', '=like', f'{prefix}-%')
        ], order='name desc', limit=1)

        last_number = 0
        if last_lot:
            _logger.info(">>> Found last lot: %s", last_lot.name)
            match = re.search(r'-(\d+)$', last_lot.name)
            if match:
                last_number = int(match.group(1))

        generated_name = f"{prefix}-{str(last_number + 1).zfill(4)}"
        _logger.info(">>> Generated New Lot Name: %s", generated_name)

        # 3. Create or Find the Lot record
        # We need an actual stock.lot record to assign it to lot_producing_id (Many2one)
        new_lot = self.env['stock.lot'].create({
            'name': generated_name,
            'product_id': self.product_id.id,
            'company_id': self.company_id.id,
        })
        _logger.info(">>> Created New Stock Lot Record ID: %s", new_lot.id)

        # 4. Assign to the MO Header Field
        self.write({'lot_producing_id': new_lot.id})
        _logger.info(">>> Assigned Lot %s to MO Header (lot_producing_id)", generated_name)

        # 5. Sync with Move Lines
        # This ensures the 'Finished Product' move lines also get the same lot
        for move in self.move_finished_ids.filtered(lambda m: m.product_id == self.product_id):
            if not move.move_line_ids:
                move._generate_serial_numbers()

            for line in move.move_line_ids:
                line.write({
                    'lot_id': new_lot.id,
                    'quantity': self.product_qty  # Optional: sets produce qty to demand
                })
                _logger.info(">>> Updated Move Line ID %s with Lot ID %s", line.id, new_lot.id)

        return True