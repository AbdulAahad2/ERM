# Invoice Journal Sync Module for Odoo 18

## Overview
This module synchronizes tax and total amounts from journal items to invoice lines, with full support for multi-currency scenarios.

## Features
- **Currency-aware synchronization**: Tax and total amounts are displayed in the currency from journal items
- **Multi-currency support**: If a journal item is in USD, tax and total are shown in USD
- **Company currency preservation**: Other fields remain in the company's default currency (PKR in your case)
- **Automatic computation**: Amounts are automatically calculated and updated
- **Manual sync option**: Includes a server action for manual synchronization if needed

## Fields Added

### Invoice Line Fields:
1. **Journal Currency**: The currency from the journal item
2. **Tax Amount (Journal Currency)**: Tax amount in the journal item's currency
3. **Total Amount (Journal Currency)**: Total amount (subtotal + tax) in the journal item's currency

## Installation

1. Copy the `invoice_journal_sync` folder to your Odoo addons directory:
   ```bash
   cp -r invoice_journal_sync /path/to/odoo/addons/
   ```

2. Update the addons list:
   - Go to Apps menu
   - Click "Update Apps List"
   - Search for "Invoice Journal Sync"

3. Install the module:
   - Click on the module
   - Click "Install"

## Usage

### Automatic Sync
Once installed, the module automatically:
- Detects the currency from journal items
- Calculates tax amounts from applied taxes
- Displays tax and total in the journal item's currency
- Keeps other fields in company default currency

### Viewing the Fields
1. Open any invoice (Sales/Purchase)
2. Go to the "Invoice Lines" tab
3. You'll see three new columns (visible when multi-currency is enabled):
   - **Journal Currency**
   - **Tax Amount (Journal Currency)**
   - **Total Amount (Journal Currency)**

### Manual Sync (if needed)
If you need to manually trigger synchronization:
1. Open an invoice
2. Click "Action" dropdown
3. Select "Sync Journal to Invoice Lines"

## Example Scenarios

### Scenario 1: USD Invoice Item with PKR Company
- Company Currency: PKR
- Journal Item Currency: USD
- Result:
  - Price Unit: Shows in PKR (company default)
  - Subtotal: Shows in PKR (company default)
  - **Journal Currency**: USD
  - **Tax Amount**: Shows in USD
  - **Total Amount**: Shows in USD

### Scenario 2: PKR Invoice Item
- Company Currency: PKR
- Journal Item Currency: PKR
- Result:
  - All amounts including tax and total show in PKR

## Technical Details

### Models Extended:
- `account.move.line`: Added computed fields for journal currency, tax amount, and total amount
- `account.move`: Added method for manual synchronization

### Dependencies:
- `account` (base accounting module)

### Computed Fields Logic:
```python
@api.depends('currency_id', 'tax_ids', 'price_subtotal', 'price_total', 'move_id.line_ids')
def _compute_journal_amounts(self):
    # Takes currency from line's currency_id
    # Calculates tax as difference between price_total and price_subtotal
    # Stores both tax and total in the journal currency
```

## Configuration

### Multi-Currency Setup
Ensure multi-currency is enabled in your Odoo instance:
1. Go to Accounting > Configuration > Settings
2. Enable "Multi-Currencies"
3. Configure exchange rates as needed

### User Permissions
The new fields are visible to users with "Multi-Currency" access rights.

## Customization

### Modifying Field Visibility
Edit `views/account_move_views.xml` to change field visibility:
```xml
<field name="journal_tax_amount" optional="show"/>
<!-- Change to optional="hide" to hide by default -->
```

### Adding More Fields
Extend `models/account_move_line.py` to add additional computed fields following the same pattern.

## Troubleshooting

### Fields Not Showing
- Ensure multi-currency is enabled
- Check user has appropriate access rights
- Verify module is properly installed

### Amounts Not Computing
- Check that tax_ids are properly configured on invoice lines
- Verify currency_id is set on the move line
- Try manual sync using the server action

### Currency Not Matching
- Ensure journal entries have correct currency_id set
- Check company currency settings
- Verify exchange rates are configured

## Support
For issues or questions, please contact your Odoo administrator or the module developer.

## License
LGPL-3

## Version
18.0.1.0.0

## Author
Your Company
