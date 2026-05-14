# MPS – Replenish All Periods
### Odoo 18 Custom Module

---

## Problem Statement

In standard Odoo 18, the **Master Production Schedule (MPS)** allows users to plan demand across multiple future periods (e.g., 4 months). However, when the user presses **"Replenish"** or **"Order Once"**, Odoo only generates procurement orders for the **first/current forecast bucket** (e.g., January). The remaining planned periods (February, March, April) are silently ignored.

This means a planner who has set up demand across a full quarter must manually press "Replenish" once per month—or wait for the scheduler to eventually process future buckets as they become the current period.

---

## Solution

This module overrides `action_replenish` on `mrp.production.schedule` to iterate over **all active forecast periods** with a positive `replenish_qty`, generating Manufacturing Orders and Purchase Orders for every configured period in a single click.

---

## What Changes

| | Standard Odoo 18 | With This Module |
|---|---|---|
| Periods processed on "Replenish" | First/current period only | **All** periods with `replenish_qty > 0` |
| MO/PO creation | Current month only | All configured months/weeks |
| Lead time handling | Applied to current period | Applied per-period (each period back-scheduled independently) |
| Vendor PO merging | Standard (within current period) | Standard (across all periods via shared procurement group) |
| Duplicate prevention | Standard Odoo deduplication | Standard Odoo deduplication (unchanged) |
| Scheduler compatibility | N/A | Fully compatible |

---

## Technical Architecture

```
action_replenish(based_on_lead_time)          ← OVERRIDDEN
│
├── _mps_collect_replenish_states()           ← returns ALL states (not [:1])
│
├── for each state:
│     _mps_build_procurements_for_state()     ← builds Procurement namedtuple
│     │
│     ├── _mps_get_procurement_date()         ← date_start or date_start - lead_time
│     ├── _mps_get_replenishment_origin()     ← MPS/WH/PROD/2025-02-01
│     └── _mps_get_procurement_values()       ← date_planned, group_id, warehouse, route
│           └── _mps_get_or_create_procurement_group()
│
└── procurement.group.run([all_procurements]) ← SINGLE BATCH RUN
      │
      ├── buy route     → purchase.order (PO)
      ├── manufacture   → mrp.production (MO)
      └── deduplication → merge with existing open orders
```

### Key Design Decision: Single `procurement.group.run()` Call

All procurement objects collected across all periods are passed to `procurement.group.run()` in **one batch**. This is critical because:

1. **Vendor PO Merging**: Odoo merges PO lines for the same vendor + currency + delivery address + lead window into a single PO. This only works when all procurements are visible in the same `run()` call.
2. **Deduplication**: Odoo checks for existing stock moves before creating new ones. A batch run ensures the check sees all planned movements at once.
3. **Route Evaluation**: Each product's applicable route (buy vs. manufacture) is evaluated once per procurement without interference.

---

## No Database Changes

This module creates:
- **Zero** new models
- **Zero** new database columns
- **Zero** new database tables
- **Zero** XML views or UI changes

It is safe to install and uninstall without any data migration or schema changes.

---

## Installation

1. Copy the `mps_replenish_all_periods/` folder into your Odoo addons path.
2. Update the App List in Odoo Settings.
3. Install **MPS – Replenish All Periods**.

### Dependencies (auto-resolved)
- `mrp_mps` (Master Production Schedule)
- `mrp` (Manufacturing)
- `purchase` (Purchase)
- `stock` (Inventory)

---

## Usage

1. Go to **Manufacturing → Planning → Master Production Schedule**
2. Configure your MPS line with the desired time horizon (e.g., 4 months)
3. Enter or confirm forecast quantities across all visible period columns
4. The MPS engine will compute `replenish_qty` for each period
5. Click **Replenish** (or **Order Once**)

**Result**: Manufacturing Orders and/or Purchase Orders are created for **every period** that has a positive `replenish_qty`, not just the first one.

---

## Behavior Preservation

The following standard Odoo behaviors are fully preserved:

| Feature | Status |
|---|---|
| Forecast quantity calculation | ✅ Unchanged (standard MPS engine) |
| Safety stock logic | ✅ Unchanged |
| Lead time calculation | ✅ Extended (applied per period) |
| Procurement rules (buy/mfg/transit) | ✅ Unchanged (delegated to `stock.rule`) |
| Vendor selection | ✅ Unchanged (`product._select_seller`) |
| PO line merging by vendor | ✅ Preserved (via shared procurement group) |
| MO creation and BOM resolution | ✅ Unchanged (handled by `mrp.rule`) |
| Stock reservations | ✅ Unchanged |
| Multi-company isolation | ✅ `company_id` propagated to all values |
| `run_scheduler` compatibility | ✅ This module does not touch the scheduler |
| MPS grid UI | ✅ Completely unchanged |

---

## Configuration

No additional configuration is required.

The module dynamically respects:
- **Time horizon**: Monthly, weekly, or any custom period configuration
- **Number of periods**: Works for any number of visible buckets (2, 4, 12, etc.)
- **Route configuration**: Reads routes from schedule line → product → product category
- **Lead times**: Reads from vendor pricelist, product fields, and company security days

---

## Traceability

Created MOs and POs will have an **Origin** field set to:

```
MPS/{WAREHOUSE_CODE}/{PRODUCT_REF}/{DATE_START}
```

Example:
```
MPS/WH/CHAIR-BLK/2025-02-01
MPS/WH/CHAIR-BLK/2025-03-01
MPS/WH/CHAIR-BLK/2025-04-01
```

This makes it immediately clear which MPS period triggered each order.

---

## Developer Notes

### Overridden Method

Only **one method** is overridden in the standard MPS model:

```
mrp.production.schedule.action_replenish(based_on_lead_time=False)
```

All other methods are **new private helpers** prefixed with `_mps_` to avoid name collisions with existing Odoo methods or future Odoo upgrades.

### Upgrade Safety

The `_mps_` prefix on all helper methods ensures no accidental override of standard Odoo methods in future versions. The only override is `action_replenish`, which is the documented public API for MPS replenishment.

### Calling `super()`

`super().action_replenish()` is **intentionally not called** in the override. The base method only processes the first period. Calling it before or after our logic would either:
- Process the first period twice (if called before), or
- Be a no-op after our code already handled all periods (if called after, wasting resources)

Instead, the override replicates the essential post-processing steps:
- `self.action_compute_forecast()` — refreshes MPS grid
- `self._get_replenishment_order_notification()` — returns UI toast

Both of these are standard MPS methods that exist on `mrp.production.schedule`.
