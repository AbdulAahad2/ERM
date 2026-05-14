# -*- coding: utf-8 -*-
# =============================================================================
# tests/test_mps_replenish_all_periods.py
#
# Functional tests for the MPS All-Periods replenishment extension.
# Run with:  python odoo-bin -i mps_replenish_all_periods --test-enable
#
# These tests verify that pressing "Replenish" on an MPS schedule
# with N configured future periods generates procurement orders for
# ALL N periods, not just the first one.
# =============================================================================

from unittest.mock import patch, MagicMock
from datetime import date, datetime, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'mps_all_periods')
class TestMpsReplenishAllPeriods(TransactionCase):
    """
    Test suite for mps_replenish_all_periods.

    Tests verify the override of action_replenish() on mrp.production.schedule
    to process all forecast period states instead of just the first one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ── Company and Warehouse ─────────────────────────────────────────
        cls.company = cls.env.company
        cls.warehouse = cls.env.ref('stock.warehouse0')

        # ── Product for manufacture route ─────────────────────────────────
        cls.product_mfg = cls.env['product.product'].create({
            'name': 'Test MPS Product (Manufacture)',
            'type': 'consu',
            'produce_delay': 5,
            'days_to_purchase': 2,
        })
        manufacture_route = cls.env.ref(
            'mrp.route_warehouse0_manufacture', raise_if_not_found=False
        )
        if manufacture_route:
            cls.product_mfg.write({'route_ids': [(4, manufacture_route.id)]})

        # ── Product for buy route ─────────────────────────────────────────
        cls.product_buy = cls.env['product.product'].create({
            'name': 'Test MPS Product (Buy)',
            'type': 'consu',
            'purchase_delay': 3,
        })
        buy_route = cls.env.ref(
            'purchase_stock.route_warehouse0_buy', raise_if_not_found=False
        )
        if buy_route:
            cls.product_buy.write({'route_ids': [(4, buy_route.id)]})

    # =========================================================================
    # Helper: create MPS schedule + synthetic forecast states
    # =========================================================================

    def _create_schedule(self, product, num_periods=4, replenish_qty_per_period=50.0):
        """
        Create an MPS schedule and mock forecast states for ``num_periods``
        consecutive months, each with the given ``replenish_qty``.

        Real MPS forecast states are normally computed by the MPS engine
        (_compute_mrp_production_schedule_state / action_compute_forecast).
        For unit tests we create them directly.
        """
        schedule = self.env['mrp.production.schedule'].create({
            'product_id': product.id,
            'warehouse_id': self.warehouse.id,
            'company_id': self.company.id,
        })

        today = date.today().replace(day=1)
        for i in range(num_periods):
            ds = today.replace(month=(today.month + i - 1) % 12 + 1,
                               year=today.year + (today.month + i - 1) // 12)
            # Compute period end: first day of next month minus one day
            if ds.month == 12:
                de = date(ds.year + 1, 1, 1) - timedelta(days=1)
            else:
                de = date(ds.year, ds.month + 1, 1) - timedelta(days=1)

            self.env['mrp.production.schedule.state'].create({
                'production_schedule_id': schedule.id,
                'date_start': ds,
                'date_stop': de,
                'replenish_qty': replenish_qty_per_period if i < num_periods else 0.0,
                'forecast_qty': replenish_qty_per_period * 1.1,
            })

        return schedule

    # =========================================================================
    # Test 1: _mps_collect_replenish_states returns ALL periods
    # =========================================================================

    def test_collect_replenish_states_returns_all_periods(self):
        """
        _mps_collect_replenish_states() must return ALL forecast states with
        replenish_qty > 0, not just the first one.
        """
        NUM_PERIODS = 4
        schedule = self._create_schedule(self.product_mfg, num_periods=NUM_PERIODS)

        states = schedule._mps_collect_replenish_states()

        self.assertEqual(
            len(states), NUM_PERIODS,
            msg=(
                f"Expected {NUM_PERIODS} states from _mps_collect_replenish_states, "
                f"got {len(states)}."
            )
        )

    def test_collect_replenish_states_excludes_zero_qty(self):
        """
        Periods with replenish_qty = 0 must be excluded from the result.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=4)

        # Zero out the last two periods
        states = schedule.forecast_ids.sorted('date_start')
        states[2].replenish_qty = 0.0
        states[3].replenish_qty = 0.0

        result = schedule._mps_collect_replenish_states()
        self.assertEqual(len(result), 2)

    def test_collect_replenish_states_sorted_by_date(self):
        """
        Returned states must be sorted ascending by date_start.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=4)
        states = schedule._mps_collect_replenish_states()
        dates = [s.date_start for s in states]
        self.assertEqual(dates, sorted(dates))

    # =========================================================================
    # Test 2: Lead time calculation
    # =========================================================================

    def test_lead_time_manufacture_product(self):
        """
        Lead time for a manufacture-route product must include produce_delay
        and days_to_purchase.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        lead_time = schedule._mps_get_product_lead_time_days()

        expected_min = self.product_mfg.produce_delay + self.product_mfg.days_to_purchase
        self.assertGreaterEqual(
            lead_time, expected_min,
            "Lead time for manufacture product should include produce_delay + days_to_purchase"
        )

    def test_lead_time_based_on_lead_time_false(self):
        """
        When based_on_lead_time=False, procurement date must equal date_start.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        target_date = date(2026, 6, 1)
        proc_dt = schedule._mps_get_procurement_date(target_date, based_on_lead_time=False)

        self.assertEqual(proc_dt.date(), target_date)

    def test_lead_time_based_on_lead_time_true_future_date(self):
        """
        When based_on_lead_time=True and date is far future, procurement date
        must be BEFORE date_start (back-scheduled by lead time).
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        far_future = date(2030, 1, 1)
        proc_dt = schedule._mps_get_procurement_date(far_future, based_on_lead_time=True)

        self.assertLess(
            proc_dt.date(), far_future,
            "Procurement date with lead time should be before period date_start"
        )

    def test_lead_time_clamped_to_now_if_past(self):
        """
        When back-scheduling would produce a past date, it must be clamped
        to the current datetime (never in the past).
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        past_date = date(2020, 1, 1)  # Far in the past
        proc_dt = schedule._mps_get_procurement_date(past_date, based_on_lead_time=True)

        self.assertGreaterEqual(
            proc_dt, datetime.now() - timedelta(seconds=5),
            "Procurement date should be clamped to now when lead-time pushes it into the past"
        )

    # =========================================================================
    # Test 3: Origin string format
    # =========================================================================

    def test_replenishment_origin_format(self):
        """
        Origin string must follow MPS/{WAREHOUSE}/{PRODUCT}/{DATE} format.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        origin = schedule._mps_get_replenishment_origin(
            date(2025, 3, 1), date(2025, 3, 31)
        )
        self.assertTrue(
            origin.startswith('MPS/'),
            "Origin must start with 'MPS/'"
        )
        self.assertIn('2025-03-01', origin)
        self.assertIn(self.warehouse.code, origin)

    # =========================================================================
    # Test 4: Procurement group reuse
    # =========================================================================

    def test_procurement_group_reused_across_calls(self):
        """
        Calling _mps_get_or_create_procurement_group() twice for the same
        schedule must return the same group record (no duplicates created).
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        group1 = schedule._mps_get_or_create_procurement_group()
        group2 = schedule._mps_get_or_create_procurement_group()
        self.assertEqual(
            group1.id, group2.id,
            "Same schedule must reuse the same procurement group"
        )

    def test_different_schedules_get_different_groups(self):
        """
        Two different MPS schedules must get different procurement groups
        to prevent cross-product PO merging.
        """
        schedule_a = self._create_schedule(self.product_mfg, num_periods=1)
        schedule_b = self._create_schedule(self.product_buy, num_periods=1)

        group_a = schedule_a._mps_get_or_create_procurement_group()
        group_b = schedule_b._mps_get_or_create_procurement_group()

        self.assertNotEqual(
            group_a.id, group_b.id,
            "Different products/schedules must have different procurement groups"
        )

    # =========================================================================
    # Test 5: action_replenish processes ALL periods (mocked procurement)
    # =========================================================================

    def test_action_replenish_processes_all_periods(self):
        """
        action_replenish() must invoke procurement.group.run() with
        one Procurement entry per active forecast period.

        We mock procurement.group.run() to avoid creating actual MOs/POs
        in the test database.
        """
        NUM_PERIODS = 4
        schedule = self._create_schedule(
            self.product_mfg,
            num_periods=NUM_PERIODS,
            replenish_qty_per_period=100.0,
        )

        captured_procurements = []

        def mock_run(procurements, raise_user_error=True):
            captured_procurements.extend(procurements)

        with patch.object(
            type(self.env['procurement.group']),
            'run',
            side_effect=mock_run,
        ):
            # Mock action_compute_forecast and _get_replenishment_order_notification
            # to avoid full MPS engine execution in unit test
            with patch.object(
                type(schedule),
                'action_compute_forecast',
                return_value=True,
            ), patch.object(
                type(schedule),
                '_get_replenishment_order_notification',
                return_value={'type': 'ir.actions.client'},
            ):
                schedule.action_replenish(based_on_lead_time=False)

        self.assertEqual(
            len(captured_procurements), NUM_PERIODS,
            msg=(
                f"Expected {NUM_PERIODS} Procurement objects (one per period), "
                f"got {len(captured_procurements)}."
            )
        )

    def test_action_replenish_skips_zero_qty_periods(self):
        """
        Periods with replenish_qty = 0 must NOT generate procurement objects.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=4)

        # Zero out 2 of the 4 periods
        states = schedule.forecast_ids.sorted('date_start')
        states[1].replenish_qty = 0.0
        states[3].replenish_qty = 0.0

        captured = []

        def mock_run(procurements, raise_user_error=True):
            captured.extend(procurements)

        with patch.object(type(self.env['procurement.group']), 'run', side_effect=mock_run), \
             patch.object(type(schedule), 'action_compute_forecast', return_value=True), \
             patch.object(type(schedule), '_get_replenishment_order_notification',
                          return_value={'type': 'ir.actions.client'}):
            schedule.action_replenish()

        # Only 2 of 4 periods have replenish_qty > 0
        self.assertEqual(len(captured), 2)

    def test_action_replenish_returns_false_when_nothing_to_do(self):
        """
        action_replenish() must return False when all forecast states have
        replenish_qty = 0 (nothing needs replenishment).
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=4)
        schedule.forecast_ids.write({'replenish_qty': 0.0})

        result = schedule.action_replenish()
        self.assertFalse(result)

    # =========================================================================
    # Test 6: Procurement values correctness
    # =========================================================================

    def test_procurement_values_contain_required_keys(self):
        """
        The values dict built by _mps_get_procurement_values must contain
        all required keys that Odoo's procurement rule chain expects.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        ds = date.today().replace(day=1)
        de = date.today().replace(day=28)
        proc_date = datetime.now()

        values = schedule._mps_get_procurement_values(
            date_start=ds,
            date_stop=de,
            procurement_date=proc_date,
        )

        required_keys = ['date_planned', 'date_deadline', 'group_id', 'warehouse_id', 'company_id']
        for key in required_keys:
            self.assertIn(key, values, f"Required key '{key}' missing from procurement values")

    def test_procurement_values_date_planned_matches_period(self):
        """
        date_planned in procurement values must match the period's date_start.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        ds = date(2026, 8, 1)
        de = date(2026, 8, 31)
        proc_date = datetime(2026, 8, 1)

        values = schedule._mps_get_procurement_values(ds, de, proc_date)
        self.assertEqual(values['date_planned'].date(), ds)

    def test_procurement_values_company_matches_schedule(self):
        """
        company_id in procurement values must match the schedule's company.
        """
        schedule = self._create_schedule(self.product_mfg, num_periods=1)
        values = schedule._mps_get_procurement_values(
            date.today(), date.today(), datetime.now()
        )
        self.assertEqual(values['company_id'].id, schedule.company_id.id)


# =============================================================================
# Test suite for Minimum Order Qty and Safety Stock (v2 features)
# =============================================================================

@tagged('post_install', '-at_install', 'mps_all_periods', 'mps_procurement_qty')
class TestProcurementQtyRules(TransactionCase):
    """
    Unit tests for the minimum_order_qty and safety_stock fields added to
    product.template and the _mps_adjust_procurement_qty helper on
    mrp.production.schedule.

    Tests are isolated from full MPS engine execution: we test the field
    helper methods directly on product.template and the schedule helper.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company   = cls.env.company
        cls.warehouse = cls.env.ref('stock.warehouse0')

        # Create a product with no special routes so tests control all qty logic
        cls.product = cls.env['product.product'].create({
            'name': 'Test Procurement Qty Product',
            'type': 'consu',
        })
        cls.tmpl = cls.product.product_tmpl_id

    def _make_schedule(self):
        """Return a minimal MPS schedule for cls.product."""
        return self.env['mrp.production.schedule'].create({
            'product_id': self.product.id,
            'warehouse_id': self.warehouse.id,
            'company_id': self.company.id,
        })

    # =========================================================================
    # minimum_order_qty field tests
    # =========================================================================

    def test_moq_field_default_zero(self):
        """minimum_order_qty defaults to 0.0 (disabled)."""
        self.assertEqual(self.tmpl.minimum_order_qty, 0.0)

    def test_moq_no_rounding_when_zero(self):
        """With moq=0, _apply_minimum_order_qty returns the raw qty unchanged."""
        self.tmpl.minimum_order_qty = 0.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(1200.0), 1200.0)

    def test_moq_rounds_up_to_next_multiple(self):
        """1200 rounded up to nearest multiple of 500 is 1500."""
        self.tmpl.minimum_order_qty = 500.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(1200.0), 1500.0)

    def test_moq_exact_multiple_unchanged(self):
        """1500 is already a multiple of 500 — no change expected."""
        self.tmpl.minimum_order_qty = 500.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(1500.0), 1500.0)

    def test_moq_rounds_one_unit_up_to_full_minimum(self):
        """A single unit with moq=500 must be ordered as 500."""
        self.tmpl.minimum_order_qty = 500.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(1.0), 500.0)

    def test_moq_zero_qty_returns_zero(self):
        """Zero qty in → zero qty out regardless of moq."""
        self.tmpl.minimum_order_qty = 500.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(0.0), 0.0)

    def test_moq_non_round_minimum(self):
        """moq=300: 700 → 900 (3×300), 600 → 600 (exact), 1 → 300."""
        self.tmpl.minimum_order_qty = 300.0
        self.assertEqual(self.tmpl._apply_minimum_order_qty(700.0), 900.0)
        self.assertEqual(self.tmpl._apply_minimum_order_qty(600.0), 600.0)
        self.assertEqual(self.tmpl._apply_minimum_order_qty(1.0),   300.0)

    # =========================================================================
    # safety_stock field tests
    # =========================================================================

    def test_safety_stock_field_default_zero(self):
        """safety_stock defaults to 0.0 (disabled)."""
        self.assertEqual(self.tmpl.safety_stock, 0.0)

    def test_safety_stock_not_added_when_zero(self):
        """With safety_stock=0, no extra qty is added regardless of on-hand."""
        self.tmpl.safety_stock = 0.0
        self.assertEqual(self.tmpl._apply_safety_stock(2500.0, 0.0), 2500.0)

    def test_safety_stock_added_when_on_hand_zero(self):
        """safety_stock=2000, raw=2500, on_hand=0 → 4500."""
        self.tmpl.safety_stock = 2000.0
        self.assertEqual(self.tmpl._apply_safety_stock(2500.0, 0.0), 4500.0)

    def test_safety_stock_added_when_on_hand_negative(self):
        """safety_stock=2000, raw=2500, on_hand=-100 → 4500 (below zero counts)."""
        self.tmpl.safety_stock = 2000.0
        self.assertEqual(self.tmpl._apply_safety_stock(2500.0, -100.0), 4500.0)

    def test_safety_stock_not_added_when_on_hand_positive(self):
        """safety_stock=2000, raw=2500, on_hand=5 → 2500 (buffer already present)."""
        self.tmpl.safety_stock = 2000.0
        self.assertEqual(self.tmpl._apply_safety_stock(2500.0, 5.0), 2500.0)

    def test_safety_stock_not_added_when_on_hand_exactly_zero_boundary(self):
        """on_hand=0 is the boundary — safety stock SHOULD be added."""
        self.tmpl.safety_stock = 2000.0
        result = self.tmpl._apply_safety_stock(100.0, 0.0)
        self.assertEqual(result, 2100.0)

    # =========================================================================
    # Combined rule: _apply_procurement_qty_rules
    # =========================================================================

    def test_combined_rules_safety_then_moq(self):
        """
        safety_stock=2000, moq=500
        raw=2500, on_hand=0:
          step1: 2500 + 2000 = 4500
          step2: ceil(4500/500)*500 = 4500  (already exact)
        """
        self.tmpl.safety_stock       = 2000.0
        self.tmpl.minimum_order_qty  = 500.0
        result = self.tmpl._apply_procurement_qty_rules(2500.0, 0.0)
        self.assertEqual(result, 4500.0)

    def test_combined_rules_triggers_moq_rounding_after_safety(self):
        """
        safety_stock=2000, moq=500
        raw=1200, on_hand=0:
          step1: 1200 + 2000 = 3200
          step2: ceil(3200/500)*500 = 3500
        """
        self.tmpl.safety_stock       = 2000.0
        self.tmpl.minimum_order_qty  = 500.0
        result = self.tmpl._apply_procurement_qty_rules(1200.0, 0.0)
        self.assertEqual(result, 3500.0)

    def test_combined_rules_only_moq_when_on_hand_positive(self):
        """
        safety_stock=2000, moq=500
        raw=1200, on_hand=5:
          step1: no safety (on_hand>0) → 1200
          step2: ceil(1200/500)*500 = 1500
        """
        self.tmpl.safety_stock       = 2000.0
        self.tmpl.minimum_order_qty  = 500.0
        result = self.tmpl._apply_procurement_qty_rules(1200.0, 5.0)
        self.assertEqual(result, 1500.0)

    def test_combined_rules_disabled_both(self):
        """With both fields = 0, the raw qty passes through unchanged."""
        self.tmpl.safety_stock       = 0.0
        self.tmpl.minimum_order_qty  = 0.0
        result = self.tmpl._apply_procurement_qty_rules(750.0, 0.0)
        self.assertEqual(result, 750.0)

    # =========================================================================
    # Schedule helper: _mps_adjust_procurement_qty
    # =========================================================================

    def test_schedule_helper_delegates_to_template(self):
        """
        _mps_adjust_procurement_qty on the schedule must produce the same
        result as calling _apply_procurement_qty_rules on the template directly.
        """
        self.tmpl.safety_stock       = 1000.0
        self.tmpl.minimum_order_qty  = 250.0

        schedule = self._make_schedule()
        raw_qty      = 800.0
        on_hand      = 0.0

        via_schedule = schedule._mps_adjust_procurement_qty(
            self.product, raw_qty, on_hand
        )
        via_template = self.tmpl._apply_procurement_qty_rules(raw_qty, on_hand)

        self.assertEqual(
            via_schedule, via_template,
            "_mps_adjust_procurement_qty must delegate to product template rules",
        )

    def test_schedule_helper_no_change_when_rules_disabled(self):
        """With both fields = 0, the schedule helper returns the raw qty."""
        self.tmpl.safety_stock       = 0.0
        self.tmpl.minimum_order_qty  = 0.0

        schedule = self._make_schedule()
        self.assertEqual(
            schedule._mps_adjust_procurement_qty(self.product, 999.0, 0.0),
            999.0,
        )