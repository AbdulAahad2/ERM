"""
One-time migration script.
Run this in the Odoo shell (odoo-bin shell -d YOUR_DB) after deploying the updated module:

    exec(open('/path/to/migrate_partner_tax_fields.py').read())

What it does:
  - Drops the old Many2one columns sap_sales_tax_id / sap_additional_tax_id from res_partner
  - The new Float columns sap_sales_tax_rate / sap_additional_tax_rate are created
    automatically by Odoo when the module is upgraded.
"""

import logging
_log = logging.getLogger(__name__)

cr = env.cr  # noqa: F821  (env is injected by odoo-bin shell)

# Check if old columns still exist
cr.execute("""
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'res_partner'
      AND column_name IN ('sap_sales_tax_id', 'sap_additional_tax_id')
""")
old_cols = [r[0] for r in cr.fetchall()]

if old_cols:
    _log.info("Dropping old Many2one tax columns: %s", old_cols)
    for col in old_cols:
        cr.execute(f'ALTER TABLE res_partner DROP COLUMN IF EXISTS "{col}"')
    env.cr.commit()
    _log.info("Done. Upgrade the module now to create the new Float columns.")
else:
    _log.info("Old columns not found — nothing to migrate.")