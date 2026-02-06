# Product Actual Name Module for Odoo 18

## Overview
This module adds an "Actual Name" field to products in Odoo 18, allowing you to maintain a separate searchable name while keeping the product reference code for GRN.

## Features
- Adds `actual_name` field to products
- Searchable by actual name in RFQ and Purchase Orders
- GRN (Goods Receipt Note) displays the product reference code (e.g., 0001)
- Enhanced search functionality across product forms

## Installation

1. Copy the `product_actual_name` folder to your Odoo addons directory
2. Update the apps list: Go to Apps > Update Apps List
3. Search for "Product Actual Name"
4. Click Install

## Usage

### Setting Up Products

1. Go to Inventory > Products > Products
2. Open or create a product
3. Set the **Internal Reference** (e.g., "0001")
4. Set the **Product Name** as usual
5. Set the **Actual Name** field (e.g., "Cream")

### Creating RFQ/Purchase Orders

1. Go to Purchase > Orders > Requests for Quotation
2. Create a new RFQ
3. When adding product lines, you can now search by:
   - Product Name
   - Internal Reference (0001)
   - **Actual Name (Cream)**
   - Barcode

The product will be displayed with the actual name in the RFQ/PO.

### Goods Receipt (GRN)

When receiving goods through the GRN:
- Products will be displayed with their Internal Reference (0001)
- The standard product name is used for identification

## Example Scenario

**Product Setup:**
- Internal Reference: `0001`
- Product Name: `Product 0001`
- Actual Name: `Cream`

**In RFQ/PO:**
- Search: Type "Cream" → Product `[0001] Cream` appears
- The product line shows the actual name for easier identification

**In GRN:**
- Product shows as `[0001] Product 0001`
- Uses the standard reference for warehouse operations

## Technical Details

### Module Structure
```
product_actual_name/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── product_template.py
│   └── product_product.py
└── views/
    ├── product_template_views.xml
    └── purchase_order_views.xml
```

### Key Customizations

1. **Product Model**: Extended with `actual_name` field
2. **Name Search**: Custom `_name_search` method to include actual_name
3. **Display Context**: Context-aware `name_get` method
4. **Purchase Context**: Special context flags for RFQ/PO behavior

## Compatibility
- Odoo Version: 18.0
- Dependencies: product, purchase, stock

## License
LGPL-3

## Support
For issues or questions, please contact your Odoo administrator.
