from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    """
    SAP Pricing section in General Settings.

    ── How per-user role assignment works ──────────────────────────────────────
    The module category 'SAP Pricing' is defined with exclusive=True in
    sap_pricing_security.xml.  Odoo automatically renders an exclusive category
    as a radio-button selector on every user's form view under the Access Rights
    tab — no extra code is required.

    To assign a role to a user:
      Settings → Users & Companies → Users → [select user] → Access Rights tab
      → look for the "SAP Pricing" section → choose User or Administrator.

    ── Why implied_group is NOT used here ──────────────────────────────────────
    implied_group on a res.config.settings field applies the group to ALL users
    system-wide when the checkbox is ticked in General Settings.  That is the
    correct pattern for "enable feature X for everyone" but wrong for per-user
    role management.  We rely on the standard user-form radio button instead.
    """
    _inherit = 'res.config.settings'