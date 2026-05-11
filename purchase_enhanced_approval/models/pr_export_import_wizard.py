import csv
import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseApprovalExportWizard(models.TransientModel):
    """
    Triggered from the gear ⚙ menu on the PR list view.
    Exports selected (or all) PRs as a flat CSV — one row per product line,
    repeating the PR header columns on every row so the file is self-contained
    and can be re-imported without any manual preparation.

    Columns exported
    ----------------
    pr_reference   – e.g. PR/0001  (used as the grouping key on import)
    date           – YYYY-MM-DD
    requester_login – res.users login  (imported → requester_id)
    department     – hr.department name
    warehouse      – stock.warehouse name  (Plant)
    product        – product.product internal reference, falls back to display_name
    description    – line description
    quantity       – float
    uom            – unit of measure name

    On import the approver is intentionally NOT exported so the PR is
    re-created in draft with no approver set.
    """
    _name = 'purchase.approval.export.wizard'
    _description = 'Export Purchase Requisitions'

    # Filled in by the server action via context
    approval_ids = fields.Many2many(
        'purchase.approval',
        string='Requests to Export',
    )
    file_data = fields.Binary(string='Download File', readonly=True)
    file_name = fields.Char(default='purchase_requisitions.csv')
    state = fields.Selection([('choose', 'Choose'), ('done', 'Done')], default='choose')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # The server action passes active_ids through context
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            res['approval_ids'] = [(6, 0, active_ids)]
        return res

    def action_export(self):
        self.ensure_one()

        approvals = self.approval_ids
        if not approvals:
            raise UserError(_('No Purchase Requisitions selected for export.'))

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            'pr_reference',
            'date',
            'requester_login',
            'department',
            'warehouse',
            'product_reference',
            'description',
            'quantity',
            'uom',
        ])

        for pr in approvals.sorted('name'):
            base = [
                pr.name,
                pr.date.strftime('%Y-%m-%d') if pr.date else '',
                pr.requester_id.login if pr.requester_id else '',
                pr.department_id.name if pr.department_id else '',
                pr.warehouse_id.name if pr.warehouse_id else '',
            ]
            if pr.line_ids:
                for line in pr.line_ids:
                    product = line.product_id
                    ref = product.default_code or product.display_name
                    writer.writerow(base + [
                        ref,
                        line.description or '',
                        line.quantity,
                        line.product_uom_id.name if line.product_uom_id else '',
                    ])
            else:
                # Export the PR header even if it has no lines yet
                writer.writerow(base + ['', '', '', ''])

        csv_bytes = output.getvalue().encode('utf-8')
        self.write({
            'file_data': base64.b64encode(csv_bytes),
            'file_name': 'purchase_requisitions.csv',
            'state': 'done',
        })

        # Stay open so the user can click Download
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class PurchaseApprovalImportWizard(models.TransientModel):
    """
    Accepts a CSV file in the same format produced by the export wizard.
    Groups rows by pr_reference and creates one draft purchase.approval
    per unique reference, with lines attached.

    Rules
    -----
    * Requester  → set from requester_login column (falls back to current user)
    * Department → matched by name (must exist)
    * Warehouse  → matched by name (must exist)
    * Approver   → intentionally NOT set; PR is created in draft
    * state      → always 'draft'

    If a pr_reference already exists in the database the rows are SKIPPED
    and reported back to the user so nothing is duplicated.
    """
    _name = 'purchase.approval.import.wizard'
    _description = 'Import Purchase Requisitions from CSV'

    file_data = fields.Binary(string='CSV File', required=True)
    file_name = fields.Char()
    result_message = fields.Text(string='Import Result', readonly=True)
    state = fields.Selection([('choose', 'Choose'), ('done', 'Done')], default='choose')

    def action_import(self):
        self.ensure_one()

        if not self.file_data:
            raise UserError(_('Please upload a CSV file first.'))

        raw = base64.b64decode(self.file_data)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')

        reader = csv.DictReader(io.StringIO(text))

        required_cols = {'pr_reference', 'department', 'product_reference', 'quantity'}
        if not required_cols.issubset(set(reader.fieldnames or [])):
            raise UserError(_(
                'CSV is missing required columns.\n'
                'Required: %s\nFound: %s'
            ) % (', '.join(sorted(required_cols)),
                 ', '.join(reader.fieldnames or [])))

        # ── Build a dict: pr_reference → { header_info, lines: [...] }
        grouped = {}
        row_errors = []

        for i, row in enumerate(reader, start=2):  # row 1 is the header
            ref = (row.get('pr_reference') or '').strip()
            if not ref:
                row_errors.append(f'Row {i}: missing pr_reference, skipped.')
                continue

            if ref not in grouped:
                grouped[ref] = {
                    'date': row.get('date', '').strip(),
                    'requester_login': row.get('requester_login', '').strip(),
                    'department': row.get('department', '').strip(),
                    'warehouse': row.get('warehouse', '').strip(),
                    'lines': [],
                }

            product_ref = (row.get('product_reference') or '').strip()
            qty_raw = (row.get('quantity') or '').strip()

            # Skip empty-line rows (PR header with no products)
            if not product_ref and not qty_raw:
                continue

            try:
                qty = float(qty_raw) if qty_raw else 1.0
            except ValueError:
                row_errors.append(f'Row {i}: invalid quantity "{qty_raw}", defaulting to 1.')
                qty = 1.0

            grouped[ref]['lines'].append({
                'product_ref': product_ref,
                'description': (row.get('description') or '').strip(),
                'quantity': qty,
            })

        if not grouped:
            raise UserError(_('No valid rows found in the CSV file.'))

        # ── Check for already-existing references
        existing_names = self.env['purchase.approval'].search(
            [('name', 'in', list(grouped.keys()))]
        ).mapped('name')

        skipped = []
        to_create = {}
        for ref, data in grouped.items():
            if ref in existing_names:
                skipped.append(ref)
            else:
                to_create[ref] = data

        # ── Resolve lookups once for efficiency
        # Users
        logins = {d['requester_login'] for d in to_create.values() if d['requester_login']}
        users_by_login = {
            u.login: u
            for u in self.env['res.users'].search([('login', 'in', list(logins))])
        }

        # Departments
        dept_names = {d['department'] for d in to_create.values() if d['department']}
        depts_by_name = {
            dep.name: dep
            for dep in self.env['hr.department'].search([('name', 'in', list(dept_names))])
        }

        # Warehouses
        wh_names = {d['warehouse'] for d in to_create.values() if d['warehouse']}
        whs_by_name = {
            wh.name: wh
            for wh in self.env['stock.warehouse'].search([('name', 'in', list(wh_names))])
        }

        # Products — try default_code first, then display_name
        all_product_refs = set()
        for data in to_create.values():
            for line in data['lines']:
                if line['product_ref']:
                    all_product_refs.add(line['product_ref'])

        products_by_ref = {}
        if all_product_refs:
            # Try internal reference (default_code) first
            by_code = {
                p.default_code: p
                for p in self.env['product.product'].search(
                    [('default_code', 'in', list(all_product_refs))]
                )
                if p.default_code
            }
            products_by_ref.update(by_code)
            # Fall back to display_name for refs not matched by code
            unmatched = all_product_refs - set(by_code.keys())
            if unmatched:
                by_name = {
                    p.display_name: p
                    for p in self.env['product.product'].search(
                        [('name', 'in', list(unmatched))]
                    )
                }
                products_by_ref.update(by_name)

        # ── Create PRs
        created_refs = []
        creation_errors = []

        PurchaseApproval = self.env['purchase.approval']

        for ref, data in to_create.items():
            dept = depts_by_name.get(data['department'])
            if not dept:
                creation_errors.append(
                    f'{ref}: department "{data["department"]}" not found — skipped.'
                )
                continue

            requester = users_by_login.get(data['requester_login']) or self.env.user
            warehouse = whs_by_name.get(data['warehouse'])

            # Parse date
            pr_date = False
            if data['date']:
                try:
                    from datetime import datetime
                    pr_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
                except ValueError:
                    pass  # will default to today

            # Build line vals
            line_vals = []
            line_errors = []
            for line in data['lines']:
                product = products_by_ref.get(line['product_ref'])
                if not product:
                    line_errors.append(
                        f'  • Product "{line["product_ref"]}" not found — line skipped.'
                    )
                    continue
                line_vals.append((0, 0, {
                    'product_id': product.id,
                    'description': line['description'] or product.display_name,
                    'quantity': line['quantity'],
                }))

            if line_errors:
                creation_errors.append(
                    f'{ref}: some lines skipped:\n' + '\n'.join(line_errors)
                )

            pr_vals = {
                # Let the sequence generate a new name — we cannot reuse old names
                # because the sequence counter won't know about them.
                # The original ref is stored as a note in the chatter.
                'department_id': dept.id,
                'requester_id': requester.id,
                'state': 'draft',
                # approver_id intentionally omitted → stays False/draft
            }
            if pr_date:
                pr_vals['date'] = pr_date
            if warehouse:
                pr_vals['warehouse_id'] = warehouse.id
            if line_vals:
                pr_vals['line_ids'] = line_vals

            new_pr = PurchaseApproval.create(pr_vals)
            # Record the original reference in the chatter for traceability
            new_pr.message_post(
                body=_('Imported from CSV. Original reference: <b>%s</b>') % ref
            )
            created_refs.append(f'{new_pr.name}  ← was {ref}')

        # ── Build result message
        lines_out = []
        if created_refs:
            lines_out.append(
                _('✅  %d PR(s) created:\n') % len(created_refs)
                + '\n'.join(f'   {r}' for r in created_refs)
            )
        if skipped:
            lines_out.append(
                _('⚠️  %d PR(s) skipped (reference already exists):\n') % len(skipped)
                + '\n'.join(f'   {r}' for r in skipped)
            )
        if creation_errors:
            lines_out.append(
                _('❌  Errors:\n') + '\n'.join(f'   {e}' for e in creation_errors)
            )
        if row_errors:
            lines_out.append(
                _('ℹ️  Row warnings:\n') + '\n'.join(f'   {e}' for e in row_errors)
            )

        self.write({
            'result_message': '\n\n'.join(lines_out) or _('Nothing to import.'),
            'state': 'done',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }