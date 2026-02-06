# Invoice Journal Sync - Module Structure

## Directory Structure
```
invoice_journal_sync/
├── __init__.py
├── __manifest__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── account_move.py
│   └── account_move_line.py
├── views/
│   └── account_move_views.xml
└── security/
    └── ir.model.access.csv
```

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         INVOICE                                  │
│                                                                   │
│  Company Currency: PKR (Default)                                │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    JOURNAL ITEMS TAB                             │
│                                                                   │
│  Journal Entry 1:                                                │
│  - Currency: USD                                                 │
│  - Amount: $100                                                  │
│  - Tax: $10                                                      │
│                                                                   │
│  Journal Entry 2:                                                │
│  - Currency: PKR                                                 │
│  - Amount: 10,000 PKR                                           │
│  - Tax: 1,000 PKR                                               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │   MODULE PROCESSING   │
                    │                       │
                    │  1. Read Currency     │
                    │  2. Calculate Tax     │
                    │  3. Calculate Total   │
                    └───────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INVOICE LINES TAB                             │
│                                                                   │
│  Line 1 (from USD Journal Entry):                               │
│  - Price Unit: 28,000 PKR (displayed in company currency)      │
│  - Subtotal: 28,000 PKR (displayed in company currency)        │
│  - Journal Currency: USD ←─────────────────┐                   │
│  - Tax Amount: $10 USD ←───────────────────┼─ FROM JOURNAL     │
│  - Total Amount: $110 USD ←────────────────┘   ITEM CURRENCY   │
│                                                                   │
│  Line 2 (from PKR Journal Entry):                               │
│  - Price Unit: 10,000 PKR (company currency)                   │
│  - Subtotal: 10,000 PKR (company currency)                     │
│  - Journal Currency: PKR                                        │
│  - Tax Amount: 1,000 PKR                                        │
│  - Total Amount: 11,000 PKR                                     │
└─────────────────────────────────────────────────────────────────┘
```

## Field Mapping

```
JOURNAL ITEM                           INVOICE LINE
================                       ===================
currency_id          ────────────────> journal_currency_id
(price_total -                         journal_tax_amount
 price_subtotal)     ────────────────> (in journal currency)
price_total          ────────────────> journal_total_amount
                                       (in journal currency)

                     ╔════════════════════════════════╗
                     ║  EXISTING FIELDS UNCHANGED:   ║
                     ║  - price_unit (PKR)           ║
                     ║  - price_subtotal (PKR)       ║
                     ║  - discount (PKR)             ║
                     ╚════════════════════════════════╝
```

## Computation Logic

```python
For each invoice line:
    
    1. Get Currency:
       journal_currency_id = line.currency_id OR company.currency_id
    
    2. Calculate Tax:
       journal_tax_amount = line.price_total - line.price_subtotal
       (in journal_currency_id)
    
    3. Calculate Total:
       journal_total_amount = line.price_total
       (in journal_currency_id)
    
    4. Display:
       - Show journal_currency_id
       - Show journal_tax_amount with currency symbol
       - Show journal_total_amount with currency symbol
```

## Multi-Currency Example

### Before Module Installation:
```
Invoice Lines:
┌──────────────┬──────────────┬──────────────┐
│ Description  │ Subtotal     │ Total        │
├──────────────┼──────────────┼──────────────┤
│ Product A    │ 28,000 PKR   │ 30,800 PKR   │
│ Product B    │ 10,000 PKR   │ 11,000 PKR   │
└──────────────┴──────────────┴──────────────┘
```

### After Module Installation:
```
Invoice Lines:
┌──────────────┬──────────────┬──────────────┬──────────┬──────────────┬──────────────┐
│ Description  │ Subtotal     │ Total        │ Currency │ Tax (Cur)    │ Total (Cur)  │
├──────────────┼──────────────┼──────────────┼──────────┼──────────────┼──────────────┤
│ Product A    │ 28,000 PKR   │ 30,800 PKR   │ USD      │ $10.00       │ $110.00      │
│ Product B    │ 10,000 PKR   │ 11,000 PKR   │ PKR      │ 1,000 PKR    │ 11,000 PKR   │
└──────────────┴──────────────┴──────────────┴──────────┴──────────────┴──────────────┘
                                              ▲           ▲               ▲
                                              │           │               │
                                         NEW FIELDS ADDED BY MODULE
```
