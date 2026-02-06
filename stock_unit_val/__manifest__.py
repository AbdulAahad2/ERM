{
    "name": "Lot Valuation in Delivery Popup",
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "summary": "Show unit cost and total valuation in lot/serial selection popup",
    "description": """
This module adds valuation information to the lot/serial number selection popup
in Delivery Orders.

Features:
- Displays Unit Cost per Lot
- Displays Total Valuation (Unit Cost × Quantity)
- Uses Stock Valuation Layers as the source of truth
- Compatible with FIFO, AVCO, and Standard Costing
""",
    "author": "Your Company",
    "license": "LGPL-3",
    "depends": [ "stock", "stock_account",
    ],
    "data": [
        "views/stock_quant_tree.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
