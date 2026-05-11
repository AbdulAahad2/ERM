# Purchase Vendor Restriction — Odoo 18

## Kya karta hai yeh module?

Jab aap kisi **Product ki Purchase tab** mein vendor set karte hain (e.g. Product ABC → Vendor: Ahmer),
toh yeh module ensure karta hai ke us product ka **Purchase Order sirf usi vendor ke saath save ho**.

Agar aap koi aur vendor (e.g. Huzaifa) select karke PO save karne ki koshish karein,
toh Odoo ek **clear error message** dega aur save nahi hone dega.

---

## Installation Steps

### Step 1 — Module folder copy karein
Is folder `purchase_vendor_restriction` ko apne Odoo addons path mein copy karein.

**Default addons path usually yahan hota hai:**
```
C:\Program Files\Odoo 18\server\odoo\addons\
```
Ya agar custom addons folder alag hai:
```
C:\odoo18\custom_addons\
```

### Step 2 — Odoo restart karein
Odoo service restart karein (Windows Services se ya terminal se):
```
net stop odoo-server-18
net start odoo-server-18
```

### Step 3 — Developer Mode ON karein
Odoo mein:
- Settings → General Settings → scroll down → **Activate Developer Mode**

### Step 4 — Module install karein
- Settings → Apps → **"Update Apps List"** click karein
- Search karein: `Purchase Vendor Restriction`
- **Install** button dabayein

---

## Use Kaise Karein

1. **Product kholein** → Purchase tab → Vendors mein vendor add karein (e.g. Ahmer)
2. **Purchase Order banayein** → Vendor mein Ahmer select karein → Product ABC add karein → ✅ Save hoga
3. **Purchase Order banayein** → Vendor mein Huzaifa select karein → Product ABC add karein → ❌ Error ayega:

```
Vendor Mismatch!

Product: ABC
Selected Vendor: Huzaifa

This product can only be purchased from: Ahmer

Please select the correct vendor or update the
product's Purchase tab to add this vendor.
```

---

## Important Notes

- Agar product ki Purchase tab mein **koi vendor set nahi** hai, toh restriction apply nahi hogi (sab vendors allow honge)
- Ek product ke saath **multiple vendors** set kar sakte hain Purchase tab mein — sab allowed honge
- Yeh validation **save karte waqt** trigger hoti hai

---

## Files Structure

```
purchase_vendor_restriction/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── purchase_order.py      ← Main validation logic
└── security/
    └── ir.model.access.csv
```
