# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _compute_is_multiple_invoice_enable(self):
        """Compute if multiple invoice is enabled from configuration"""
        val = self.env['ir.default'].sudo()._get(
            'res.config.settings', 'multiple_invoice')
        for record in self:
            record.is_multiple_invoice_enable = val

    def _get_commission(self):
        """Get commission count for this order"""
        for order in self:
            pos_commissions = self.env['pos.commission'].search(
                [('order_id', '=', order.id)])
            order.commission_count = len(pos_commissions)

    commission_employee_id = fields.Many2one('hr.employee', string='Commission Employee', readonly=True)
    commission_employee_name = fields.Char(string='Commission Employee Name', readonly=True)
    
    is_commission = fields.Boolean(string='Is Commission')
    is_multiple_invoice_enable = fields.Boolean(
        string='Use Hr Employee Config', compute='_compute_is_multiple_invoice_enable')
    commission_count = fields.Integer(
        string='Commission Count', compute='_get_commission', readonly=True)

    def action_view_commission(self):
        action = self.env.ref(
            'pos_sales_commission.commission_pos_commission_view').read()[0]
        action['domain'] = [('order_id', '=', self.id)]
        return action

    @api.model
    def _process_order(self, order, draft, *args, **kwargs):
        """Override to add commission processing"""
        _logger.info("=" * 80)
        _logger.info("=== COMMISSION PROCESSING START ===")
        _logger.info("=" * 80)
        
        # Clean invalid relational fields
        if isinstance(order, dict):
            invalid_keys = [key for key in list(order.keys()) if key.startswith('<-')]
            if invalid_keys:
                _logger.info(f"Removing invalid relational keys: {invalid_keys}")
                for key in invalid_keys:
                    order.pop(key, None)
        
        # Extract commission data before parent processes the order
        commission_data = self._extract_commission_data(order)
        
        # Call parent to create the order
        _logger.info("Calling super()._process_order()...")
        order_id = super()._process_order(order, draft, *args, **kwargs)
        _logger.info(f"✓ Order created with ID: {order_id}")
        
        if not order_id:
            _logger.error("✗ Order creation failed")
            _logger.info("=" * 80)
            return order_id
        
        # Process commission if applicable
        self._process_commission(order_id, commission_data, order)
        
        _logger.info("=" * 80)
        _logger.info("=== COMMISSION PROCESSING END ===")
        _logger.info("=" * 80)
        return order_id

    def _extract_commission_data(self, order):
        """Extract commission data from order dict"""
        if not isinstance(order, dict):
            return {}
        
        # Handle both direct structure and nested 'data' structure
        order_data = order.get('data', order)
        
        # Safety check
        if not order_data:
            return {}
        
        is_commission = order_data.get('is_commission', False)
        commission_employee_id = order_data.get('commission_employee_id')
        commission_employee_name = order_data.get('commission_employee_name')
        
        # Handle null/false conversions from JavaScript
        if commission_employee_id in (False, 0, None):
            commission_employee_id = None
        else:
            try:
                commission_employee_id = int(commission_employee_id)
            except (ValueError, TypeError):
                commission_employee_id = None
        
        result = {
            'is_commission': is_commission,
            'commission_employee_id': commission_employee_id,
            'commission_employee_name': commission_employee_name,
        }
        
        _logger.info(f"Extracted commission data: {result}")
        return result

    def _process_commission(self, order_id, commission_data, order):
        """Process commission for an order"""
        pos_order = self.browse(order_id)
        
        is_commission = commission_data.get('is_commission', False)
        commission_employee_id = commission_data.get('commission_employee_id')
        commission_employee_name = commission_data.get('commission_employee_name')
        
        # Save commission employee info to order
        if commission_employee_id:
            try:
                pos_order.write({
                    'commission_employee_id': commission_employee_id,
                    'commission_employee_name': commission_employee_name,
                    'is_commission': is_commission,
                })
                _logger.info(f"✓ Saved commission employee: {commission_employee_name} (ID: {commission_employee_id})")
            except Exception as e:
                _logger.error(f"✗ Error saving commission employee: {e}", exc_info=True)
        
        # Check if we should create commission
        if not is_commission:
            _logger.info("⚠ is_commission is False - skipping")
            return
        
        if not commission_employee_id:
            _logger.warning("⚠ No commission_employee_id - skipping")
            return
        
        # Verify employee
        employee = self.env['hr.employee'].browse(commission_employee_id)
        if not employee.exists():
            _logger.error(f"✗ Employee {commission_employee_id} does not exist")
            return
        
        if not employee.is_commission_applicable:
            _logger.warning(f"⚠ Employee {employee.name} not commission applicable")
            return
        
        if not employee.is_veterinarian:
            _logger.warning(f"⚠ Employee {employee.name} is not a veterinarian")
            return
        
        _logger.info(f"✓ Creating commission for employee: {employee.name}")
        
        # Get commission configuration
        commission_id = self.get_commission_config(order)
        if not commission_id:
            _logger.error("✗ No commission configuration found")
            return
        
        commission_vals = self.env['pos.sale.commission'].browse([commission_id])
        _logger.info(f"✓ Commission config: {commission_vals.name}, rule: {commission_vals.commission_rule}")
        
        # Get commission product
        product = self.env['product.product'].search([('is_commission_product', '=', True)], limit=1)
        if not product:
            _logger.error("✗ No commission product found (is_commission_product = True)")
            return
        
        _logger.info(f"✓ Commission product: {product.name} (ID: {product.id})")
        
        # Get settings
        auto_confirm = self.env['ir.default'].sudo()._get(
            'res.config.settings', 'auto_confirm_at_order_validation')
        
        order_data = order.get('data', order)
        partner = order_data.get('user_id')
        
        # Create commission
        try:
            if commission_vals.commission_rule == 'amount':
                self._create_amount_based_commission(
                    pos_order, employee, commission_vals, 
                    product, partner, auto_confirm
                )
            else:
                self._create_product_based_commission(
                    pos_order, employee, commission_vals,
                    product, partner, auto_confirm
                )
            _logger.info("✓ Commission created successfully")
        except Exception as e:
            _logger.error(f"✗ Error creating commission: {e}", exc_info=True)

    def get_commission_config(self, order):
        """Get commission configuration from POS session"""
        order_data = order.get('data', order)
        
        if not order_data:
            return None
        
        pos_session_id = order_data.get('session_id') or order_data.get('pos_session_id')
        
        if not pos_session_id:
            _logger.warning(f"No session_id found in order")
            return None
        
        session = self.env['pos.session'].search([('id', '=', pos_session_id)], limit=1)
        
        if not session:
            _logger.warning(f"POS session {pos_session_id} not found")
            return None
        
        if session and session.config_id and session.config_id.sale_commission_id:
            _logger.info(f"✓ Commission config: {session.config_id.sale_commission_id.name}")
            return session.config_id.sale_commission_id.id
        
        return None

    def _create_amount_based_commission(self, pos_order, employee, 
                                       commission_config, commission_product, 
                                       partner, auto_confirm):
        """Create commission based on order amount"""
        amount_total = pos_order.amount_total
        commission_amount = commission_config.compute_commission_based_on_amount(
            amount_total, commission_config.id)
        
        _logger.info(f"Amount-based commission: {commission_amount}")
        
        if commission_amount > 0:
            # For amount-based, we don't have a specific product, use commission product
            self._create_commission_record(
                commission_product, commission_amount, partner, 
                employee.id, pos_order.id, auto_confirm,
                sold_product_id=commission_product.id  # Use commission product as sold product
            )

    def _create_product_based_commission(self, pos_order, employee,
                                        commission_config, commission_product,
                                        partner, auto_confirm):
        """Create commission based on products"""
        create_commission_mode = self.env['ir.default'].sudo()._get(
            'res.config.settings', 'create_commission')
        
        lines = pos_order.lines
        if not lines:
            _logger.warning("⚠ No order lines found")
            return
        
        _logger.info(f"Processing {len(lines)} lines, mode: {create_commission_mode}")
        
        if create_commission_mode == 'multiple':
            # Separate commission for each line
            for line in lines:
                commission_amount = commission_config.compute_commission(
                    line.product_id.id, line.price_unit, line.qty, commission_config.id
                )
                
                if commission_amount > 0:
                    self._create_commission_record(
                        commission_product, commission_amount, partner,
                        employee.id, pos_order.id, auto_confirm,
                        sold_product_id=line.product_id.id  # Pass the actual sold product
                    )
        else:
            # Single commission for all lines
            self._create_single_commission(
                lines, pos_order.id, employee.id, partner, 
                commission_config, auto_confirm
            )

    def _create_single_commission(self, lines, order_id, employee_id,
                                  partner, commission_config, auto_confirm):
        """Create a single commission record for all lines"""
        val_line = []
        total_commission_amount = 0.0
        
        for line in lines:
            commission_amount = commission_config.compute_commission(
                line.product_id.id, line.price_unit, line.qty, commission_config.id
            )
            
            if commission_amount > 0:
                total_commission_amount += commission_amount
                val_line.append([0, 0, {
                    'product_id': line.product_id.id,  # This is the SOLD product
                    'commission_amount': commission_amount,
                    'user_id': partner,
                    'employee_id': employee_id,
                    'order_id': order_id,
                    'qty': line.qty,
                    'price_unit': line.price_unit,
                }])
        
        if total_commission_amount > 0:
            vals = {
                'user_id': partner,
                'employee_id': employee_id,
                'order_id': order_id,
                'pos_commission_line_ids': val_line,
                'commission_amount': total_commission_amount,
            }
            self._create_and_confirm_commission(vals, auto_confirm)

    def _create_commission_record(self, commission_product, commission_amount, partner,
                                  employee_id, order_id, auto_confirm, sold_product_id=None):
        """Create a single commission record
        
        Args:
            commission_product: The product used for commission accounting
            commission_amount: Amount of commission
            sold_product_id: The actual product that was sold (for display)
        """
        # Use sold_product_id if provided, otherwise use commission_product
        display_product_id = sold_product_id if sold_product_id else commission_product.id
        
        val_line = [[0, 0, {
            'product_id': display_product_id,  # Use the SOLD product for display
            'commission_amount': commission_amount,
            'user_id': partner,
            'employee_id': employee_id,
            'order_id': order_id,
            'qty': 1,
            'price_unit': commission_amount,
        }]]
        
        vals = {
            'user_id': partner,
            'employee_id': employee_id,
            'order_id': order_id,
            'pos_commission_line_ids': val_line,
            'commission_amount': commission_amount,
        }
        
        self._create_and_confirm_commission(vals, auto_confirm)

    def _create_and_confirm_commission(self, vals, auto_confirm):
        """Create and optionally confirm commission"""
        try:
            commission = self.env['pos.commission'].create([vals])
            
            if commission:
                _logger.info(f"✓✓✓ Commission created: ID {commission.id}")
                
                if auto_confirm:
                    commission.state = "confirm"
                    _logger.info("✓ Commission auto-confirmed")
            else:
                _logger.error("✗ Failed to create commission")
        except Exception as e:
            _logger.error(f"✗ Exception creating commission: {e}", exc_info=True)
