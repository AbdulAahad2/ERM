import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def action_open_auto_generate_lots(self):
        self.ensure_one()
        _logger.info(">>> Starting Vendor Lot Generation for Move ID: %s", self.id)

        # 1. Get the prefix from the Vendor
        vendor = self.picking_id.partner_id
        prefix = vendor.lot_code if vendor and vendor.lot_code else "LOT"
        _logger.info(">>> Vendor: %s | Prefix Used: %s", vendor.name if vendor else "None", prefix)

        # 2. Check if we have move lines. If not, Odoo might not have initialized them.
        if not self.move_line_ids:
            _logger.info(">>> No move lines found. Creating a default line based on demand.")
            self.env['stock.move.line'].create({
                'move_id': self.id,
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'picking_id': self.picking_id.id,
                'quantity': self.product_uom_qty,
            })

        # 3. Filter lines that need a lot name (Lot/Serial Number column)
        lines_to_update = self.move_line_ids.filtered(lambda l: not l.lot_name and not l.lot_id)
        _logger.info(">>> Found %s lines to update", len(lines_to_update))

        counter = 1
        for line in lines_to_update:
            generated_name = f"{prefix}-{str(counter).zfill(3)}"

            # Writing to 'lot_name' fills the "Lot/Serial Number" column for new lots
            line.write({
                'lot_name': generated_name,
                'quantity': line.quantity or 1.0
            })
            _logger.info(">>> Assigned Lot: %s to Move Line ID: %s", generated_name, line.id)
            counter += 1

        # 4. Refresh the view so the user sees the numbers immediately
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
            'views': [[self.env.ref('stock.view_stock_move_operations').id, 'form']],
        }


import logging
import re  # Important: This must be here for the incrementing to work
from datetime import datetime
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    manuf_lot_code = fields.Char(string="Manufacturing Lot Code")


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_custom_lot_name(self):
        """Logic to split Manufacturing (Sequence) and Purchasing (Date)"""
        # --- MANUFACTURING LOGIC: PRODUCT_CODE-0001 ---
        if self.production_id or self.raw_material_production_id or self.env.context.get(
                'active_model') == 'mrp.production':
            prefix = self.product_id.manuf_lot_code or "MFG"

            # Search existing lots for this specific product and prefix
            domain = [
                ('product_id', '=', self.product_id.id),
                ('name', '=like', f'{prefix}-%')
            ]
            last_lot = self.env['stock.lot'].search(domain, order='id desc', limit=1)

            last_number = 0
            if last_lot:
                # Use regex to find the digits after the last hyphen
                # e.g., from "PROD-0004" it finds "0004"
                numbers = re.findall(r'-(\d+)$', last_lot.name)
                if numbers:
                    last_number = int(numbers[-1])

            new_number = str(last_number + 1).zfill(4)
            return f"{prefix}-{new_number}"

        # --- PURCHASE/RECEIPT LOGIC: VENDOR_CODE-MM-DD-YY ---
        else:
            vendor = self.picking_id.partner_id
            prefix = vendor.lot_code if vendor and vendor.lot_code else "LOT"
            date_str = datetime.now().strftime('%m-%d-%y')
            return f"{prefix}-{date_str}"

    def action_generate_serial(self):
        """Force the '+' button in Manufacturing to use our custom logic"""
        self.ensure_one()
        if self.has_tracking != 'none':
            new_name = self._get_custom_lot_name()
            # This sets the value for the Odoo widget
            self.next_lot_not_instanciated = new_name

            # For Odoo 18 Manufacturing, we also apply it to the move lines immediately
            if not self.move_line_ids:
                self.action_show_details()  # Ensure lines are initialized

            for line in self.move_line_ids:
                if not line.lot_name and not line.lot_id:
                    line.lot_name = new_name
            return True
        return super().action_generate_serial()

    def action_open_auto_generate_lots(self):
        """Your custom button logic"""
        self.ensure_one()
        generated_name = self._get_custom_lot_name()

        if not self.move_line_ids:
            # Create a default line if none exists
            self.env['stock.move.line'].create({
                'move_id': self.id,
                'picking_id': self.picking_id.id,
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom.id,
                'location_id': self.location_id.id,
                'location_dest_id': self.location_dest_id.id,
                'quantity': self.product_uom_qty,
            })

        self.invalidate_recordset(['move_line_ids'])
        for line in self.move_line_ids.filtered(lambda l: not l.lot_name and not l.lot_id):
            line.write({'lot_name': generated_name})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'views': [[self.env.ref('stock.view_stock_move_operations').id, 'form']],
            'context': self.env.context,
        }