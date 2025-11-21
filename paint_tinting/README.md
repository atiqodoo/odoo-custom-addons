# Paint Tinting Module for Odoo 18

## Overview

Custom paint tinting module designed for **Crown Kenya PLC** with full integration with Odoo 18 Manufacturing. This module streamlines the paint tinting process from LargoTint machine input to manufacturing order completion.

## Key Features

✅ **Dynamic Product Creation** - Automatically creates tinted products with proper naming convention  
✅ **Persistent BOM Management** - Saves recipes globally with full versioning and change tracking  
✅ **16 Pre-loaded Colorants** - Shot-to-ml-to-litre conversion (1 shot = 0.616 ml)  
✅ **Variant-Based Base Paint Selection** - Intelligent filtering by paint type and pack size  
✅ **Dual VAT Tracking** - Records both VAT-exclusive and VAT-inclusive (16%) costs  
✅ **Negative Stock Support** - Soft warnings only, allows manufacturing to proceed  
✅ **AVCO Costing Integration** - Automatic Average Cost rebalancing  
✅ **paint_colour_master Integration** - Full compatibility with existing fandeck/colour code system

## Technical Specifications

- **Odoo Version**: 18.0 Enterprise
- **Dependencies**: `base`, `product`, `stock`, `mrp`, `uom`, `paint_colour_master`
- **Costing Method**: AVCO (Anglo-Saxon Accounting)
- **UoM**: Custom Volume units (1L, 4L, 20L)
- **Architecture**: Modern Odoo 18 standards (no deprecated tags)

## Installation

### 1. Prerequisites

Ensure the following are installed and configured:
- Odoo 18 Enterprise
- `paint_colour_master` module (for fandeck and colour code management)
- PostgreSQL with proper access rights
- Manufacturing module enabled

### 2. Module Installation

```bash
# Copy module to Odoo addons directory
cp -r paint_tinting /path/to/odoo/addons/

# Update apps list in Odoo
# Navigate to: Apps > Update Apps List

# Install module
# Search for "Paint Tinting Module" and click Install
```

### 3. Initial Configuration

After installation:

1. **Verify UoM Creation**:
   - Go to `Inventory > Configuration > Units of Measure`
   - Confirm: 1L, 4L, 20L are in the Volume category

2. **Verify Colorants**:
   - Go to `Paint Tinting > Products > Colorants`
   - Confirm all 16 colorants (C1-C16) are created

3. **Configure Base Paints**:
   - Go to `Paint Tinting > Products > Base Paints`
   - For each base paint product:
     - Set `Is Base Paint` = True
     - Select appropriate `Paint Type`
     - Create variants using "Base Type" attribute

4. **Enable Negative Stock** (if not already enabled):
   - Go to `Inventory > Configuration > Settings`
   - Enable "Negative Stock" under Stock > Products

## Usage

### Tinting Workflow (7 Steps)

#### Step 1: Launch Wizard
Navigate to: `Paint Tinting > Operations > Tint New Paint`

#### Step 2: Paint Details
Fill in:
- **Fandeck**: Select from paint_colour_master
- **Colour Code**: Auto-filtered by fandeck
- **Colour Name**: Auto-filled
- **Paint Type**: Supergloss, Vinylsilk, etc.
- **Pack Size**: 1L, 4L, or 20L
- **Base Variant**: Auto-filtered by paint type

Click **Next: Colorant Input**

#### Step 3: Colorant Input
- All 16 colorants are pre-loaded
- Enter **Shots** from LargoTint machine
- System auto-calculates:
  - ml (shots × 0.616)
  - Litres (ml ÷ 1000)
  - Costs (VAT-exclusive and VAT-inclusive)
  - Stock availability

#### Step 4: Stock Warnings
- Red warnings show if stock insufficient
- **You can proceed anyway** - negative stock is allowed

#### Step 5: Review Costs
Check the **Cost Summary** tab:
- Base paint cost
- Colorant costs
- Total cost (Excl. VAT and Incl. VAT)

#### Step 6: Create Product & BOM
Click **Create Tinted Product & MO**

System automatically:
1. Creates dynamic product: `[Base] – [Code] – [Colour Name]`
2. Creates persistent BOM with all components
3. Creates Manufacturing Order
4. Opens MO for processing

#### Step 7: Complete Manufacturing
In the opened MO:
1. Click **Start**
2. Click **Done**
3. Materials consumed (even if negative stock)

## Data Structure

### Product Naming Convention
```
[Base Variant Name] – [Colour Code] – [Colour Name]

Example:
"Pastel Base 4L – KPLC – Kenya Blue"
```

### BOM Structure
```
Finished Product: Tinted Paint (1 unit)
Components:
  - Base Paint: 1 × [pack size UoM]
  - Colorant C1: X litres (if shots > 0)
  - Colorant C2: Y litres (if shots > 0)
  ...
  - Colorant C16: Z litres (if shots > 0)
```

### Cost Calculation
```
Total Cost (Excl. VAT) = Base Cost + Σ(Colorant Cost/L × Litres)
Total Cost (Incl. VAT) = Total Cost (Excl. VAT) × 1.16
```

## Module Structure

```
paint_tinting/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── product_template.py      # Product extensions
│   ├── mrp_bom.py                # BOM extensions
│   └── mrp_bom_line.py           # BOM line extensions
├── wizards/
│   ├── __init__.py
│   ├── tint_wizard.py            # Main wizard logic
│   └── tint_wizard_colorant_line.py
├── views/
│   ├── tint_wizard_views.xml     # Wizard forms
│   ├── product_template_views.xml
│   ├── mrp_bom_views.xml
│   └── menu_views.xml
├── data/
│   ├── uom_data.xml              # 1L, 4L, 20L UoM
│   ├── product_category_data.xml
│   └── colorant_products_data.xml # 16 pre-loaded colorants
├── security/
│   └── ir.model.access.csv
└── static/
    └── description/
        └── icon.png
```

## Modern Odoo 18 Compliance

This module follows Odoo 18 best practices:

✅ Uses `<list>` instead of deprecated `<tree>` in views  
✅ No `<attribute>` tags in XML  
✅ Proper field decorations with `decoration-*` attributes  
✅ `column_invisible` instead of `invisible` for list columns  
✅ Modern widget usage  
✅ Proper `TransientModel` for wizards  
✅ Computed stored fields with proper dependencies  

## Troubleshooting

### Issue: Colorants not showing in wizard
**Solution**: Ensure colorants have `is_colorant = True` and `colorant_code` set

### Issue: Base variants not appearing
**Solution**: 
- Check product has `is_base_paint = True`
- Verify `paint_type` is set
- Ensure variants are created with "Base Type" attribute

### Issue: Stock warnings even with sufficient stock
**Solution**: Check UoM conversions - colorants should use Litre UoM

### Issue: Costs not calculating
**Solution**: Ensure `standard_price` is set on base and colorant products

## Phase 2 Features (Future)

- 🔄 Recipe re-use (search existing tinted products)
- 🏷️ Auto label printing after MO completion
- 📊 Barcode generation on tinted products
- 🔌 Direct API integration with LargoTint machine

## Support

For issues or questions:
- **Module Developer**: ATIQ (Odoo Developer & System Administrator)
- **Company**: Crown Kenya PLC
- **System**: odoo.mzaramopaintsandwallpaper.com

## License

LGPL-3

## Version History

**v18.0.1.0.0** (Initial Release)
- Complete tinting workflow
- 16 pre-loaded colorants
- Persistent BOM with VAT tracking
- Negative stock support
- Full paint_colour_master integration
