# -*- coding: utf-8 -*-
# ============================================================================
# Module: mps_replenish_all_periods
# Purpose: Extend Odoo 18 MPS to replenish ALL visible forecast periods,
#          not just the current/first bucket.
#
# Standard Odoo Limitation:
#   action_replenish() on mrp.production.schedule only generates procurement
#   orders for the FIRST/CURRENT forecast bucket (e.g., "this month").
#   Remaining configured future periods are completely ignored.
#
# What this module adds:
#   When the user presses "Replenish" or "Order Once" in the MPS screen,
#   ALL visible forecast periods with replenish_qty > 0 are processed.
#   Manufacturing Orders and Purchase Orders are generated for every period,
#   respecting lead times, routes, vendor merging, and procurement rules.
#
# What this module does NOT do:
#   - Add new models                  ✗
#   - Add new database fields         ✗
#   - Create duplicate MPS screens    ✗
#   - Override scheduler behavior     ✗
#   - Modify procurement rules        ✗
#   - Touch existing MPS UI layout    ✗
#
# Author:   Custom Development
# Version:  18.0.1.0.0
# License:  LGPL-3
# ============================================================================
{
    'name': 'MPS – Replenish All Periods',
    'version': '18.0.1.0.0',
    'summary': (
        'Extends MPS replenishment to process all visible forecast periods '
        'instead of only the current period.'
    ),
    'description': """
MPS Replenish All Periods
=========================
Standard Odoo 18 MPS Limitation
--------------------------------
When you configure a Master Production Schedule with a time horizon of
4 months and enter forecast quantities across all 4 months, pressing
"Replenish" in Odoo standard only generates orders for the FIRST period.
The remaining 3 months of planned quantities are ignored.

What This Module Does
---------------------
This module overrides ``action_replenish`` on ``mrp.production.schedule``
to iterate over ALL active forecast period states with a positive
``replenish_qty``.

For each period the module:

* Reads the computed ``replenish_qty`` from ``mrp.production.schedule.state``
* Applies lead-time back-scheduling when ``based_on_lead_time=True``
* Builds a standard Odoo ``procurement.group.Procurement`` namedtuple
* Passes all collected procurements to ``procurement.group.run()`` in one call

The single ``procurement.group.run()`` call ensures:

* Vendor merging (same supplier → merged PO lines)
* MO consolidation via procurement groups
* Deduplication of existing open orders
* Correct route evaluation (manufacture vs. buy per product/category)

Technical Notes
---------------
* Only ``mrp.production.schedule`` is inherited (``_inherit``)
* ``mrp.production.schedule.state`` is read-only (no field additions)
* Uses ``procurement.group.Procurement`` namedtuple (stable Odoo API)
* Fully dynamic: works for monthly, weekly, or custom horizon configs
* Multi-company safe (company_id propagated through all procurement values)
* Scheduler-compatible: does not interfere with ``run_scheduler``
""",
    'author': 'Custom Development',
    'category': 'Manufacturing/Manufacturing',
    'website': '',
    'license': 'LGPL-3',

    # ── Dependencies ──────────────────────────────────────────────────────
    # mrp_mps  : Master Production Schedule (provides the models we extend)
    # mrp      : Manufacturing Orders (needed for manufacture route)
    # purchase : Purchase Orders (needed for buy route)
    # stock    : Stock moves, procurement groups, locations
    'depends': [
        'mrp_mps',   # Core dependency: provides mrp.production.schedule
        'mrp',       # Manufacturing route + MO creation
        'purchase',  # Buy route + PO creation
        'stock',     # Procurement groups, stock rules, locations
    ],

    # ── Data files ────────────────────────────────────────────────────────
    'data': [
        # View extension: adds Minimum Order Qty + Safety Stock to product form
        'views/product_template_views.xml',
    ],

    # ── Module flags ──────────────────────────────────────────────────────
    'installable': True,
    'auto_install': False,
    'application': False,

    # ── Technical info ────────────────────────────────────────────────────
    # This module has NO database migrations: zero new fields or tables.
    # It is safe to install/uninstall without affecting existing MPS data.
}
