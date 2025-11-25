# Enhanced Stock Card Report for Odoo 18

## Overview
Complete stock movement report with AVCO costing, purchase tracking, and POS sales analysis.

## Features
- **Physical Movements**: IN/OUT/Balance quantities with all move types
- **AVCO Costing**: Unit cost and inventory value from stock.valuation.layer
- **Purchase Tracking**: Unit prices and amounts including VAT
- **POS Integration**: Selling prices and amounts including taxes (per order)
- **Running Totals**: Cumulative tracking of purchases and sales
- **100% Reconciliation**: Matches stock quantities, inventory values, and financial records
- **Multiple Exports**: PDF and Excel formats

## Installation

1. **Copy module to Odoo addons directory**:
   ```bash
   cp -r enhanced_stock_card /path/to/odoo/addons/
   ```

2. **Install Python dependencies**:
   ```bash
   pip install xlsxwriter
   ```

3. **Update apps list** in Odoo:
   - Settings → Apps → Update Apps List

4. **Install module**:
   - Search for "Enhanced Stock Card Report"
   - Click Install

## Requirements
- Odoo 18.0 Enterprise or Community
- Anglo-Saxon accounting
- Automated inventory valuation
- AVCO (Average Cost) costing method
- Python library: xlsxwriter

## Dependencies
- stock
- stock_account
- purchase_stock
- sale_stock
- point_of_sale
- mrp

## Usage

1. Navigate to **Inventory → Reporting → Stock Card Report**
2. Configure filters:
   - Select products (or leave empty for all)
   - Choose warehouse or specific locations
   - Set date range
   - Enable/disable internal transfers
   - Choose grouping options
3. Click **Print PDF** or **Export Excel**

## Report Columns (16 Total)

### Movement Information
1. Date
2. Reference
3. Type
4. Partner

### Physical Quantities
5. IN (quantity received)
6. OUT (quantity delivered)
7. Balance (running total)

### Valuation (AVCO)
8. Unit Cost
9. Value (this move)
10. Running Value

### Purchase Data (Incl. VAT)
11. **Purchase Unit Price** (NEW)
12. Purchase Amount
13. Running Purchase Total

### POS Data (Incl. Taxes)
14. **POS Unit Price** (NEW)
15. POS Amount
16. Running POS Total

## POS Sales: Per Order vs Per Session

**IMPORTANT**: POS sales are recorded **per individual order** (transaction), NOT per session.

This means:
- Each POS sale appears as a separate line in the report
- Different orders may have different unit prices (discounts, promotions)
- Prices shown are what specific customers paid
- Running totals still reconcile with session totals

## Key Technical Details

### Data Sources
- **Physical quantities**: stock.move
- **AVCO costs**: stock.valuation.layer
- **Purchase amounts**: purchase.order.line.price_total (incl. VAT)
- **POS amounts**: pos.order.line.price_subtotal_incl (incl. taxes)

### Movement Types Supported
- Purchase receipts
- Sales deliveries
- POS sales (per order)
- Manufacturing consumption & production
- Internal transfers (optional display)
- Inventory adjustments
- Scrap
- Returns (purchase & sales)
- Landed costs

### Reconciliation
- Closing quantity = stock.quant.quantity ✓
- Closing value = sum(stock.valuation.layer.value) ✓
- Purchase total = sum(purchase invoices with VAT) ✓
- POS total = sum(POS session sales with taxes) ✓

## Configuration Notes

### Odoo 18 Compatibility
- Uses `<list>` views (not deprecated `<tree>`)
- Avoids `<attribute>` tags
- Compatible with Odoo 18 Enterprise and Community

### Costing Method
Ensure products are configured with:
- Costing Method: Average Cost (AVCO)
- Inventory Valuation: Automated

### Accounting
Module requires Anglo-Saxon accounting with perpetual inventory.

## File Structure
```
enhanced_stock_card/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── stock_card_wizard.py
├── report/
│   ├── __init__.py
│   ├── stock_card_report.py
│   └── stock_card_templates.xml
├── views/
│   ├── stock_card_wizard_views.xml
│   └── menu_views.xml
├── security/
│   └── ir.model.access.csv
├── static/
│   └── description/
│       ├── index.html
│       └── (icon.png)
└── README.md
```

## License
LGPL-3

## Author
Your Company

## Version
18.0.1.0.0

## Support
For issues or questions, contact your system administrator.
