# Stock Receipt Label Auto Print
## Installation, Configuration & Usage Guide
### Odoo 18 — Version 1.0.0

---

## 1. What This Module Does

When a warehouse operator validates a purchase receipt (`WH/IN/xxxxx`) in the
**Purchase** or **Inventory** app, a popup wizard opens automatically listing
every product and lot that was just received.

The operator can:

- Review what was received (product, lot/SN, quantity)
- Adjust how many labels to print per product
- Deselect any products they don't want to label
- Choose the label format (ZPL for thermal, PDF sheet, Dymo)
- Click **Print Labels** — labels are sent to the configured IoT printer or
  downloaded as a browser PDF/ZPL file

### Key benefits over Odoo's built-in silent auto-print

| Feature | Built-in silent print | This module |
|---|---|---|
| Operator sees what is being printed | No | **Yes** |
| Adjust label qty before printing | No | **Yes** |
| Skip individual products | No | **Yes** |
| Works with existing IoT printer setup | Yes | **Yes** (reuses same pipeline) |
| Lot/SN label printing | Separate step | **Combined in one popup** |

---

## 2. Installation

### Prerequisites

- Odoo 18 (Community or Enterprise)
- `stock` module installed (Inventory app)
- `product` module installed (included with stock)
- *(Optional)* `iot` module for direct IoT Box thermal printing

### Steps

1. **Copy the module** to your custom addons directory:
   ```
   c:\odoo18\custom_addon\stock_receipt_label_auto_print\
   ```

2. **Restart the Odoo server**:
   ```bash
   # Windows — from the Odoo root directory
   python odoo-bin -c odoo.conf --stop-after-init
   # Then start normally
   python odoo-bin -c odoo.conf
   ```
   Or restart the Windows service if Odoo runs as a service.

3. **Update the app list**:
   In Odoo → Settings → Apps → click **Update Apps List**

4. **Install the module**:
   Search for `Stock Receipt Label Auto Print` → click **Install**

5. **Verify installation**:
   Go to Inventory → Configuration → Operation Types. On any incoming
   operation type form, you should see a new **"Receipt Label Popup"**
   section below the existing "Print on Validation" group.

---

## 3. Configuration

### Step 1 — Enable the popup on your Receipt operation type

1. Go to **Inventory → Configuration → Operation Types**
2. Click on your **Receipts** operation type (e.g. "paints shop: Receipts")
3. Open the **Technical** tab (or scroll to the printing section)
4. Find the **Receipt Label Popup** group:

   ```
   ┌────────────────────────────────────────────────┐
   │ Receipt Label Popup                            │
   │                                                │
   │ Label Popup on Receipt  [✓] Enabled            │
   │ Default Format          [ZPL Labels ▼]         │
   │ Default Scope           [Product Labels ▼]     │
   └────────────────────────────────────────────────┘
   ```

5. Tick **Label Popup on Receipt**
6. Choose your **Default Format**:
   - `ZPL Labels` — for Bixolon SLP-DX420, Zebra, or any ZPL thermal printer
   - `4 x 12` — A4 PDF sheet with 48 labels per page
   - `2 x 7 with price` — PDF with price shown
   - `Dymo` — for Dymo label printers
7. Choose your **Default Scope**:
   - `Product Labels` — prints using the product's EAN/internal reference barcode
   - `Lot / SN Labels` — prints the lot number as the barcode
   - `Both` — prints both in sequence
8. **Save**

### Step 2 — Configure your IoT printer (Bixolon SLP-DX420)

The popup reuses Odoo's existing IoT printer infrastructure. Labels are routed
to the IoT Box automatically when you link your report to a printer device.

1. Go to **Inventory → Configuration → Printers** (requires IoT module)
2. Click on your **Bixolon SLP-DX420** device
3. In the **Reports** tab, add:
   - `Product Label (ZPL)` — for product labels
   - `Lot/Serial Number (ZPL)` — for lot/SN labels
4. Save

When the popup prints, Odoo sends the ZPL job to the IoT Box via WebSocket,
which delivers it to the Bixolon printer over USB or network.

**Without IoT:** If no printer is linked to the report, the browser will
download a `.txt` ZPL file or open a PDF print dialog instead.

### Step 3 — (Optional) Adjust log level for debugging

Add to your `odoo.conf` or logging configuration:

```ini
[logger_receipt_label]
level = DEBUG
handlers = file
qualname = stock_receipt_label_auto_print
propagate = 0
```

Or set temporarily in Odoo:
Settings → Technical → Logging → Add `stock_receipt_label_auto_print` at DEBUG level.

---

## 4. How to Use (Step-by-Step)

### Normal receipt flow

1. Open a purchase order with received goods → click **Receive Products**
   (or open the receipt directly from Inventory)

2. Confirm the done quantities on the receipt form

3. Click **Validate**

4. *(If backorder wizard appears)* → handle backorder as normal. The label
   popup will appear after the backorder decision is confirmed.

5. **The label popup opens automatically:**

   ```
   ┌─────────────────────────────────────────────────────────────────┐
   │  Print Receipt Labels                                            │
   ├─────────────────────────────────────────────────────────────────┤
   │  Receipt: WH/IN/00277                                            │
   ├───────────────────────────────────────────────────────────────  │
   │  Print: ( ) Product Labels  (•) Both  ( ) Lot/SN Labels         │
   │  Format: [ZPL Labels ▼]    Lot Label Qty: [One per lot ▼]       │
   ├───┬──────────────────────────┬──────────┬──────────┬────────────┤
   │ ☑ │ 1LTR GAMMA GLOSS (white) │          │   20.00  │ [20]       │
   │ ☑ │ 1LTR GAMMA GLOSS (black) │          │   20.00  │ [20]       │
   │ ☑ │ 2.5KG CROWN DU CO        │ LOT-2026 │    5.00  │ [5]        │
   │ ☐ │ THINNERS 5L              │          │    2.00  │ [2]        │
   ├───┴──────────────────────────┴──────────┴──────────┴────────────┤
   │  [Select All]  [Deselect All]          [Skip]  [Print Labels]   │
   └─────────────────────────────────────────────────────────────────┘
   ```

6. **Review the list** — all products with received quantities are shown

7. **Adjust if needed:**
   - Uncheck rows you don't want to label
   - Edit the **Labels** column to print a different number than received
   - Change **Format** if needed (e.g., switch ZPL → 4x12)
   - Change **Print** scope if needed

8. Click **Print Labels** — labels print to the configured IoT printer

9. Click **Skip** to close without printing

---

## 5. Troubleshooting

### Popup does not appear after Validate

**Check 1** — Is the feature enabled on the operation type?

Go to Inventory → Configuration → Operation Types → your receipt type → Technical tab.
Confirm `Label Popup on Receipt` is ticked.

**Check 2** — Is the picking type code `incoming`?

The popup only fires for operation types with code = `incoming`. Custom types
copied from another code will not trigger the popup.

**Check 3** — Were quantities actually done?

The popup only appears if at least one move_line has `quantity > 0`.
If you validated with zero quantities, the popup is suppressed.

**Check 4** — Are you seeing a backorder wizard instead?

Confirm the backorder decision first. The label popup fires on the final
validate call after backorder handling completes.

---

### Labels are not going to the printer

**Check 1** — Is the IoT module installed?

Without `iot`, labels download to the browser instead of printing.

**Check 2** — Is the report linked to the IoT device?

Inventory → Configuration → Printers → Bixolon device → Reports tab.
The `Product Label (ZPL)` and `Lot/Serial Number (ZPL)` reports must be listed.

**Check 3** — Is the IoT Box online?

Inventory → Configuration → IoT Boxes → check the box status is "Connected".

**Check 4** — Check browser console for WebSocket errors

Open Chrome DevTools → Console tab → validate a receipt → look for errors
starting with `iot.channel`.

---

### Labels print with wrong quantities

The popup shows quantities from **done** move_lines (`qty_done` field in Odoo 18
is the `quantity` field on `stock.move.line`). If the quantity looks wrong:

- Check the done quantity on the receipt's detailed operations tab
- Ensure UoM is "Units" — non-unit UoMs cannot be used as integer label counts
  (the wizard rounds to the nearest integer)

---

### Error: "Product model not defined"

This error comes from `report.stock.label_product_product_view._get_report_values`
when the `active_model` key is missing from the data dict. This should not occur
with this module but if it does, enable DEBUG logging and check the
`[_build_product_label_actions]` log lines to inspect the data dict being passed.

---

### Enable full debug logging

In Odoo, navigate to:
**Settings → Technical → Logging → Add logger**

```
Logger name:  stock_receipt_label_auto_print
Level:        DEBUG
```

Then validate a receipt and check your Odoo log file for lines starting with:
```
[button_validate]
[filter]
[build_wizard]
[_populate_lines]
[action_print]
[_build_product_label_actions]
[_build_lot_label_actions]
```

---

## 6. Label Format Reference

| Format key | Output | Best for |
|---|---|---|
| `zpl` | ZPL text (sent to thermal printer) | Bixolon SLP-DX420, Zebra GK420 |
| `zplxprice` | ZPL with price block | Price tags on thermal printer |
| `4x12` | A4 PDF — 48 labels/page | Office laser printer |
| `4x12xprice` | A4 PDF — 48 labels/page with price | Price sheets |
| `2x7xprice` | A4 PDF — 14 labels/page with price | Larger price tags |
| `4x7xprice` | A4 PDF — 28 labels/page with price | Medium price tags |
| `dymo` | Dymo-specific PDF | Dymo LabelWriter |

**For lot/SN labels**, only `zpl` and `4x12` are supported by Odoo's built-in
lot label template. Any other format automatically falls back to `4x12`.

---

## 7. Technical Architecture (for Developers)

### Module files

```
stock_receipt_label_auto_print/
├── __manifest__.py                      Module metadata, depends: stock, product
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── stock_picking_type.py            3 new fields on stock.picking.type
│   └── stock_picking.py                 Override button_validate() — single hook point
├── wizard/
│   ├── __init__.py
│   └── stock_receipt_label_wizard.py    StockReceiptLabelWizard (header)
│                                        StockReceiptLabelWizardLine (per-product row)
├── views/
│   ├── stock_picking_type_views.xml     XPath injection into operation type form
│   └── stock_receipt_label_wizard_views.xml  Popup wizard form view
├── security/
│   └── ir.model.access.csv             Read/write/create/unlink for stock.group_stock_user
└── doc/
    └── INSTALL_AND_USAGE.md            This file
```

### Execution flow

```
User: clicks Validate
  │
  ▼
stock.picking.button_validate()                    ← OVERRIDDEN
  │
  ├─► super().button_validate()                    ← standard Odoo logic runs unchanged
  │     ├─ _pre_action_done_hook()                 backorder check
  │     ├─ _action_done()                          moves processed, state → 'done'
  │     └─ _get_autoprint_report_actions()         existing silent prints (if configured)
  │
  ├─► _get_done_receipts_for_popup()               filter by code/state/flag
  │
  ├─► _build_receipt_label_wizard_action()
  │     └─ stock.receipt.label.wizard.create()
  │     └─ wizard._populate_lines()                reads done move_lines
  │
  └─► _chain_wizard_action(result, wizard_action)
        ├─ result is True        → return wizard act_window
        └─ result is do_multi_print → set wizard as anotherAction
              └─ Odoo JS: run all silent prints → then open wizard dialog

User: reviews popup, clicks Print Labels
  │
  ▼
stock.receipt.label.wizard.action_print()
  │
  ├─► _build_product_label_actions()
  │     ├─ builds quantity_by_product + custom_barcodes dicts
  │     ├─ creates minimal product.label.layout (for pricelist)
  │     ├─ _get_product_label_xml_id()             maps format → ir.actions.report
  │     └─ ir.actions.report.report_action(None, data=data)
  │
  └─► _build_lot_label_actions() (if lots selected)
        ├─ mode=lots:  lot.label.layout.process()   (standard Odoo)
        └─ mode=units: builds docids manually → ir.actions.report.report_action()
  │
  └─► return do_multi_print { reports: [...] }
        └─ Odoo JS: send to IoT Box or open browser download
```

### Design principles

1. **Single override point** — only `button_validate` is extended. No other
   stock methods are touched, ensuring forward compatibility.
2. **Zero custom printing code** — all rendering and IoT routing goes through
   `stock.label_product_product` and `stock.label_lot_template`, which are
   Odoo's own report actions. If those reports gain new features in a future
   Odoo version, this module benefits automatically.
3. **Opt-in per operation type** — the popup is off by default; each warehouse
   can configure it independently.
4. **Upgrade safety** — `_get_autoprint_report_actions` is not overridden, so
   the existing silent auto-print behaviour is completely unaffected.

---

## 8. Changelog

| Version | Date | Notes |
|---|---|---|
| 1.0.0 | 2026-05-30 | Initial release for Odoo 18 |
