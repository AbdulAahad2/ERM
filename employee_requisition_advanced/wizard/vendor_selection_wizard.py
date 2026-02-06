from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class VendorSelectionWizard(models.TransientModel):
    _name = 'vendor.selection.wizard'
    _description = 'Vendor Selection for RFQ'

    requisition_id = fields.Many2one('employee.requisition', string='Requisition', required=True)
    line_ids = fields.One2many('vendor.selection.wizard.line', 'wizard_id', string='Vendors')

    @api.model
    def default_get(self, fields_list):
        """Override to populate vendor lines from context"""
        res = super(VendorSelectionWizard, self).default_get(fields_list)

        requisition_id = self.env.context.get('default_requisition_id')
        if not requisition_id:
            return res

        requisition = self.env['employee.requisition'].browse(requisition_id)
        if not requisition.exists():
            return res

        # Collect all vendors from requisition lines
        vendor_data = {}

        for line in requisition.line_ids:
            # If vendor explicitly selected on line
            if line.vendor_id:
                if line.vendor_id.id not in vendor_data:
                    vendor_data[line.vendor_id.id] = {
                        'vendor_id': line.vendor_id.id,
                        'product_names': [],
                    }
                vendor_data[line.vendor_id.id]['product_names'].append(line.product_id.display_name)
            else:
                # Get vendors from product sellers
                for seller in line.product_id.seller_ids:
                    if seller.partner_id.id not in vendor_data:
                        vendor_data[seller.partner_id.id] = {
                            'vendor_id': seller.partner_id.id,
                            'product_names': [],
                        }
                    vendor_data[seller.partner_id.id]['product_names'].append(line.product_id.display_name)

        # Create wizard lines
        wizard_lines = []
        for vendor_id, data in vendor_data.items():
            products_str = ', '.join(set(data['product_names']))
            wizard_lines.append((0, 0, {
                'vendor_id': vendor_id,
                'products': products_str,
                'selected': True,
            }))

        if wizard_lines:
            res['line_ids'] = wizard_lines

        return res

    def action_create_rfqs(self):
        self.ensure_one()

        _logger.info("=== RFQ Creation Debug ===")
        _logger.info(f"Wizard ID: {self.id}")
        _logger.info(f"Line IDs count: {len(self.line_ids)}")

        # Debug: Print all lines
        for line in self.line_ids:
            _logger.info(
                f"Line: vendor_id={line.vendor_id.id if line.vendor_id else None}, selected={line.selected}, products={line.products}")

        PurchaseOrder = self.env['purchase.order']

        # Get selected vendors - ensure vendor_id exists
        selected_vendors = self.line_ids.filtered(lambda l: l.selected and l.vendor_id).mapped('vendor_id')

        _logger.info(f"Selected vendors: {selected_vendors.ids}")

        if not selected_vendors:
            raise UserError(_("Please select at least one vendor."))

        rfqs = self.env['purchase.order']

        for vendor in selected_vendors:
            order_lines = []

            for line in self.requisition_id.line_ids:
                # Check if this vendor is relevant for this line
                is_vendor_for_line = False
                price = 0.0

                # Case 1: Vendor explicitly selected on line
                if line.vendor_id and line.vendor_id == vendor:
                    is_vendor_for_line = True
                    seller = line.product_id.seller_ids.filtered(lambda s: s.partner_id == vendor)[:1]
                    price = seller.price if seller else line.unit_price

                # Case 2: Vendor is in product sellers
                elif not line.vendor_id:
                    seller = line.product_id.seller_ids.filtered(lambda s: s.partner_id == vendor)[:1]
                    if seller:
                        is_vendor_for_line = True
                        price = seller.price

                if is_vendor_for_line:
                    order_lines.append((0, 0, {
                        'product_id': line.product_id.id,
                        'product_qty': line.quantity,
                        'product_uom': line.product_id.uom_po_id.id,
                        'price_unit': price,
                    }))

            if order_lines:
                po = PurchaseOrder.create({
                    'partner_id': vendor.id,
                    'origin': self.requisition_id.name,
                    'order_line': order_lines,
                })
                rfqs |= po

        if not rfqs:
            raise UserError(_("No RFQs were created. Please check your vendor and product configuration."))

        # Link all created RFQs to this requisition
        self.requisition_id.write({
            'purchase_order_ids': [(6, 0, rfqs.ids)],
            'state': 'approved'
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', rfqs.ids)],
            'target': 'current',
        }


class VendorSelectionWizardLine(models.TransientModel):
    _name = 'vendor.selection.wizard.line'
    _description = 'Vendor Selection Line'

    wizard_id = fields.Many2one('vendor.selection.wizard', string='Wizard', required=True, ondelete='cascade')
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True)
    products = fields.Text(string='Products')
    selected = fields.Boolean(string='Select', default=True)