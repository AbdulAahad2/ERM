# -*- coding: utf-8 -*-
# =============================================================================
# models/product_template.py
#
# PURPOSE
# -------
# Add two procurement-control fields to product.template (and by inheritance
# to product.product):
#
#   minimum_order_qty (float)
#   ─────────────────────────
#   The smallest quantity a vendor will supply in one order.
#   When a procurement (MPS replenishment or PR line) is computed, the raw
#   requested quantity is rounded UP to the nearest multiple of this value.
#
#   Example:  minimum_order_qty = 500
#             raw required qty  = 1200
#             actual order qty  = 1500   (next multiple of 500)
#
#   A value of 0 (default) means "no minimum" – the raw quantity is used as-is.
#
#   safety_stock (float)
#   ─────────────────────
#   A buffer quantity that is ADDED to the MPS replenishment quantity whenever
#   the on-hand stock is at or below zero for the period being replenished.
#   This ensures a standing buffer is always ordered alongside the production
#   requirement.
#
#   Example:  safety_stock      = 2000
#             MPS required qty  = 2500
#             on-hand           = 0
#             actual order qty  = 4500   (2500 + 2000)
#
#   If on-hand > 0 the safety_stock is NOT added (it is already covered).
#   A value of 0 (default) means "no safety stock" – no extra quantity is added.
#
# FIELD LOCATION
# ──────────────
# Both fields are added to product.template and surfaced on the product form
# via the view extension in views/product_template_views.xml.
# product.product inherits them automatically through Odoo's delegation.
#
# =============================================================================

import math
import logging

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ── Minimum Order Quantity ────────────────────────────────────────────────

    minimum_order_qty = fields.Float(
        string='Minimum Order Qty',
        default=0.0,
        digits='Product Unit of Measure',
        help=(
            "The minimum quantity that can be ordered from a vendor in a single "
            "purchase order or purchase requisition.\n\n"
            "When MPS replenishment computes the order quantity for this product, "
            "the result is rounded UP to the nearest multiple of this value.\n\n"
            "Example: if Minimum Order Qty = 500 and the required qty is 1200, "
            "the actual order will be placed for 1500 units.\n\n"
            "Set to 0 to disable (no rounding applied)."
        ),
    )

    # ── Safety Stock ──────────────────────────────────────────────────────────

    safety_stock = fields.Float(
        string='Safety Stock',
        default=0.0,
        digits='Product Unit of Measure',
        help=(
            "Buffer quantity added to every MPS replenishment order when the "
            "forecasted on-hand stock for the period is at or below zero.\n\n"
            "This guarantees a standing inventory buffer is always rebuilt "
            "alongside the direct production requirement.\n\n"
            "Example: if Safety Stock = 2000 and MPS requires 2500 units (with "
            "zero on-hand), the actual order will be placed for 4500 units.\n\n"
            "If on-hand stock is already positive, the safety stock is NOT added "
            "because the buffer is considered covered.\n\n"
            "Set to 0 to disable."
        ),
    )

    # =========================================================================
    # Utility methods (called from mrp_production_schedule.py)
    # =========================================================================

    def _get_minimum_order_qty(self):
        """
        Return the effective minimum order quantity for this template.
        Returns 0.0 if the feature is disabled (field is 0).
        """
        self.ensure_one()
        return max(self.minimum_order_qty or 0.0, 0.0)

    def _get_safety_stock(self):
        """
        Return the effective safety stock quantity for this template.
        Returns 0.0 if the feature is disabled (field is 0).
        """
        self.ensure_one()
        return max(self.safety_stock or 0.0, 0.0)

    def _apply_minimum_order_qty(self, raw_qty):
        """
        Round ``raw_qty`` UP to the nearest multiple of minimum_order_qty.

        Args:
            raw_qty (float): The quantity computed before rounding.

        Returns:
            float: The rounded-up quantity.  Equal to raw_qty when
                   minimum_order_qty is 0.

        Examples:
            minimum_order_qty = 500, raw_qty = 1200  → 1500
            minimum_order_qty = 500, raw_qty = 1500  → 1500  (exact multiple)
            minimum_order_qty = 500, raw_qty =    1  →  500
            minimum_order_qty =   0, raw_qty = 1200  → 1200  (no-op)
        """
        self.ensure_one()
        moq = self._get_minimum_order_qty()
        if not moq or raw_qty <= 0.0:
            return raw_qty

        # math.ceil(raw_qty / moq) * moq – handles non-integer multiples cleanly
        multiplier = math.ceil(raw_qty / moq)
        rounded = multiplier * moq

        if rounded != raw_qty:
            _logger.debug(
                "[MinOrderQty] %s: raw_qty=%.4f → rounded=%.4f (moq=%.4f)",
                self.display_name, raw_qty, rounded, moq,
            )

        return rounded

    def _apply_safety_stock(self, raw_qty, forecasted_on_hand):
        """
        Add safety_stock to ``raw_qty`` when ``forecasted_on_hand`` <= 0.

        This field is intended for standalone reorder rules (min/max),
        NOT for MPS-driven BOM component ordering.  The MPS already handles
        FG-level buffering via the Safety Stock Target on the schedule form.

        For MPS component PRs, safety stock is intentionally skipped — only
        MOQ rounding is applied (see _mps_create_draft_mo_with_component_prs).

        Args:
            raw_qty (float):             Procurement qty before safety stock.
            forecasted_on_hand (float):  Expected on-hand for the period.
                                         Pass 0.0 when unknown / unavailable.

        Returns:
            float: raw_qty + safety_stock  when forecasted_on_hand <= 0,
                   raw_qty                 otherwise.
        """
        self.ensure_one()
        ss = self._get_safety_stock()
        if not ss or raw_qty <= 0.0:
            return raw_qty

        if (forecasted_on_hand or 0.0) <= 0.0:
            adjusted = raw_qty + ss
            _logger.debug(
                "[SafetyStock] %s: raw_qty=%.4f + safety_stock=%.4f → %.4f "
                "(forecasted_on_hand=%.4f)",
                self.display_name, raw_qty, ss, adjusted, forecasted_on_hand,
            )
            return adjusted

        return raw_qty

    def _apply_procurement_qty_rules(self, raw_qty, forecasted_on_hand=0.0):
        """
        Apply BOTH safety-stock and minimum-order-qty rules in the correct order:

          1. Add safety stock (if on-hand <= 0)
          2. Round up to minimum order qty

        This ordering is intentional: the safety-stock buffer is part of the
        "true requirement" that the MOQ rounding then acts upon.

        Args:
            raw_qty (float):             Base procurement quantity.
            forecasted_on_hand (float):  Forecasted on-hand for the period.

        Returns:
            float: Final adjusted procurement quantity.
        """
        self.ensure_one()
        after_safety = self._apply_safety_stock(raw_qty, forecasted_on_hand)
        after_moq    = self._apply_minimum_order_qty(after_safety)
        return after_moq