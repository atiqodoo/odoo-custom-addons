# Paint Tinting Module - Upgrade & Deployment Guide

## Pre-Installation Checklist

### System Requirements
- [ ] Odoo 18 Enterprise installed and running
- [ ] PostgreSQL database accessible
- [ ] Manufacturing module enabled
- [ ] Inventory module enabled
- [ ] `paint_colour_master` module installed and configured
- [ ] User has MRP User or MRP Manager rights

### Backup Requirements
```bash
# Backup database
pg_dump -U odoo -F c -b -v -f "/backup/before_tinting_$(date +%Y%m%d).backup" odoo_database

# Backup filestore
cp -r /path/to/odoo/filestore /backup/filestore_$(date +%Y%m%d)

# Backup addons
cp -r /path/to/odoo/addons /backup/addons_$(date +%Y%m%d)
```

## Installation Steps

### Step 1: Copy Module Files
```bash
# Stop Odoo service (Windows Server)
net stop odoo-server

# Copy module to addons directory
xcopy /E /I paint_tinting "C:\Program Files\Odoo 18\server\odoo\addons\paint_tinting"

# OR for custom addons path
xcopy /E /I paint_tinting "D:\odoo\custom_addons\paint_tinting"
```

### Step 2: Update Module List
```bash
# Start Odoo service
net start odoo-server

# In Odoo UI:
# 1. Enable Developer Mode (Settings > Activate Developer Mode)
# 2. Go to Apps
# 3. Click "Update Apps List"
# 4. Search for "Paint Tinting"
# 5. Click Install
```

### Step 3: Verify Installation
Check the following after installation:

1. **Menu Structure**:
   - Paint Tinting menu appears in main navigation
   - Operations > Tint New Paint
   - Products > Tinted Products, Base Paints, Colorants
   - Recipes (BOMs) > Tinting BOMs

2. **Data Created**:
   ```sql
   -- Verify UoM created
   SELECT name, category_id, factor_inv 
   FROM uom_uom 
   WHERE name IN ('1L', '4L', '20L');
   
   -- Verify colorants created
   SELECT COUNT(*) FROM product_template WHERE is_colorant = TRUE;
   -- Should return: 16
   
   -- Verify categories created
   SELECT name FROM product_category 
   WHERE name IN ('Tinted Paint', 'Colorants', 'Base Paints');
   ```

3. **Access Rights**:
   - MRP User can access wizard
   - MRP User can create tinted products
   - MRP Manager has full access

## Configuration Steps

### Step 4: Configure Base Paint Products

For each base paint product (e.g., Crown Supergloss):

1. **Create Product Template**:
   ```
   Name: Crown Supergloss
   Type: Storable Product
   Category: Base Paints
   UoM: Litre
   ```

2. **Enable Tinting Fields**:
   ```
   Is Base Paint: ✓ True
   Paint Type: Select (Supergloss, Vinylsilk, etc.)
   ```

3. **Create Variants Using Attributes**:
   ```
   Attribute: Base Type
   Values:
     - Pastel Base
     - Deep Base
     - Accent Base
     - Brilliant White
     - Cream
   
   Pack Size: Use 1L, 4L, 20L UoM
   ```

4. **Set Standard Price**:
   ```
   Standard Price: [Cost per unit]
   Costing Method: Average Cost (AVCO)
   Valuation: Automated (Anglo-Saxon)
   ```

### Step 5: Verify Colorant Configuration

Check each colorant (C1-C16):

```python
# In Odoo shell or via UI
colorants = env['product.template'].search([('is_colorant', '=', True)])
for colorant in colorants:
    assert colorant.uom_id.name == 'Litre', f"{colorant.name} UoM mismatch"
    assert colorant.standard_price > 0, f"{colorant.name} has no price"
    assert colorant.colorant_code, f"{colorant.name} has no code"
```

### Step 6: Configure Inventory Settings

1. **Enable Negative Stock** (if needed):
   ```
   Settings > Inventory > Products
   ☑ Allow Negative Stock
   ```

2. **Configure Stock Locations**:
   ```
   Ensure WH/Stock location exists
   Create "Tinting Station" location (optional)
   ```

3. **Set Valuation Method**:
   ```
   For all product categories:
   - Costing Method: Average Cost (AVCO)
   - Inventory Valuation: Automated
   ```

## Testing Checklist

### Test 1: Basic Tinting Flow
- [ ] Open "Tint New Paint" wizard
- [ ] Select Fandeck (e.g., Crown Colour Collection)
- [ ] Select Colour Code (filtered by fandeck)
- [ ] Verify Colour Name auto-fills
- [ ] Select Paint Type (e.g., Supergloss)
- [ ] Select Pack Size (e.g., 4L)
- [ ] Select Base Variant (filtered by paint type)
- [ ] Verify Base Cost displays
- [ ] Click "Next: Colorant Input"

### Test 2: Colorant Input
- [ ] Verify all 16 colorants pre-loaded
- [ ] Enter shots for C1 (e.g., 10 shots)
- [ ] Verify ml = 6.16 (10 × 0.616)
- [ ] Verify Litres = 0.00616 (6.16 ÷ 1000)
- [ ] Verify Available Stock shows
- [ ] Verify Unit Cost displays
- [ ] Verify Line Cost calculates (Incl. VAT)
- [ ] Enter shots for other colorants
- [ ] Check Cost Summary tab
- [ ] Verify totals calculate correctly

### Test 3: Stock Warnings
- [ ] Enter shots that exceed available stock
- [ ] Verify red decoration on stock field
- [ ] Verify warning message displays
- [ ] Confirm can still proceed
- [ ] Note: "negative stock allowed" message

### Test 4: Product Creation
- [ ] Click "Create Tinted Product & MO"
- [ ] Verify product created with format:
  ```
  [Base Variant] – [Code] – [Colour Name]
  ```
- [ ] Check product fields:
  - [ ] Category = "Tinted Paint"
  - [ ] UoM = selected pack size
  - [ ] is_tinted_product = True
  - [ ] fandeck_id set
  - [ ] colour_code_id set
  - [ ] cost_price_excl_vat calculated

### Test 5: BOM Creation
- [ ] Verify BOM created and linked to product
- [ ] Check BOM fields:
  - [ ] is_tinting_bom = True
  - [ ] total_cost_excl_vat calculated
  - [ ] total_cost_incl_vat calculated
  - [ ] fandeck_id, colour_code_id set
  - [ ] base_variant_id set
- [ ] Check BOM lines:
  - [ ] Base paint: 1 unit in pack size UoM
  - [ ] Colorants: only lines with shots > 0
  - [ ] Each line has cost_excl_vat and cost_incl_vat

### Test 6: Manufacturing Order
- [ ] Verify MO opens after creation
- [ ] Check MO fields:
  - [ ] Product = tinted product
  - [ ] BOM = newly created BOM
  - [ ] Quantity = 1
  - [ ] State = Confirmed
- [ ] Click "Start"
- [ ] Verify components reserved (or negative stock)
- [ ] Click "Done"
- [ ] Verify MO completed
- [ ] Check stock moves created

### Test 7: Cost Verification
```sql
-- Check product cost updated
SELECT 
    pt.name,
    pt.standard_price,
    pt.cost_price_excl_vat,
    pt.cost_price_incl_vat
FROM product_template pt
WHERE pt.is_tinted_product = TRUE
ORDER BY pt.create_date DESC
LIMIT 5;

-- Check BOM costs
SELECT 
    mb.id,
    pt.name as product,
    mb.total_cost_excl_vat,
    mb.total_cost_incl_vat
FROM mrp_bom mb
JOIN product_template pt ON mb.product_tmpl_id = pt.id
WHERE mb.is_tinting_bom = TRUE
ORDER BY mb.create_date DESC
LIMIT 5;
```

### Test 8: Duplicate Prevention
- [ ] Try to create same tinted product again
- [ ] Should show error: "Product already exists"
- [ ] Verify cannot proceed

### Test 9: Negative Stock Flow
- [ ] Set colorant stock to 0
- [ ] Create tinted product using that colorant
- [ ] Verify warning shows
- [ ] Proceed with creation
- [ ] Check stock after MO completion
- [ ] Verify negative stock recorded

### Test 10: Multi-UoM Testing
- [ ] Create tinted product with 1L base
- [ ] Create tinted product with 4L base
- [ ] Create tinted product with 20L base
- [ ] Verify each uses correct UoM
- [ ] Verify costs scale appropriately

## Common Issues & Solutions

### Issue 1: Colorants Not Appearing in Wizard
**Symptoms**: Colorant table empty in wizard Step 2

**Solution**:
```python
# Check colorant products exist
colorants = env['product.template'].search([('is_colorant', '=', True)])
print(f"Found {len(colorants)} colorants")

# If missing, run data file again
# Or create manually through UI
```

### Issue 2: Base Variants Not Filtered
**Symptoms**: All products show in Base Variant dropdown

**Solution**:
- Check product has `is_base_paint = True`
- Check product has `paint_type` set
- Verify domain in wizard view

### Issue 3: Cost Not Calculating
**Symptoms**: Cost fields show 0.00

**Solution**:
```python
# Check product standard_price
product = env['product.template'].browse(PRODUCT_ID)
print(f"Standard Price: {product.standard_price}")

# Update if needed
product.write({'standard_price': 100.00})
```

### Issue 4: UoM Conversion Issues
**Symptoms**: Incorrect quantities in BOM

**Solution**:
```sql
-- Check UoM configuration
SELECT 
    name, 
    category_id, 
    factor, 
    factor_inv, 
    uom_type
FROM uom_uom
WHERE name IN ('1L', '4L', '20L');

-- Verify category is Volume
SELECT * FROM uom_category WHERE name = 'Volume';
```

### Issue 5: Access Rights Error
**Symptoms**: "Access Denied" when opening wizard

**Solution**:
```bash
# Update module to reload security
# In Odoo UI:
Apps > Paint Tinting Module > Upgrade

# Or via command line:
odoo-bin -d database -u paint_tinting
```

## Upgrade from Development to Production

### Pre-Upgrade
```bash
# 1. Backup production database
pg_dump -U odoo -F c odoo_prod > prod_backup_$(date +%Y%m%d).backup

# 2. Test on development copy
psql -U odoo -d odoo_dev < prod_backup_YYYYMMDD.backup

# 3. Install/upgrade on development
odoo-bin -d odoo_dev -u paint_tinting --stop-after-init

# 4. Run all tests on development
# 5. Get user acceptance on development
```

### Production Upgrade
```bash
# 1. Schedule maintenance window
# 2. Notify users
# 3. Stop Odoo service
net stop odoo-server

# 4. Backup database
pg_dump -U odoo -F c odoo_prod > prod_backup_$(date +%Y%m%d).backup

# 5. Copy module files
xcopy /E /I paint_tinting "C:\Program Files\Odoo 18\server\odoo\addons\paint_tinting"

# 6. Start Odoo
net start odoo-server

# 7. Upgrade via UI or CLI
odoo-bin -d odoo_prod -u paint_tinting --stop-after-init

# 8. Verify installation
# 9. Run smoke tests
# 10. Notify users - system ready
```

## Rollback Procedure

If issues occur after installation:

```bash
# 1. Stop Odoo
net stop odoo-server

# 2. Restore database
psql -U odoo -d odoo_prod < prod_backup_YYYYMMDD.backup

# 3. Remove module files
rmdir /S "C:\Program Files\Odoo 18\server\odoo\addons\paint_tinting"

# 4. Start Odoo
net start odoo-server

# 5. Uninstall module (if partially installed)
# Go to Apps > Paint Tinting Module > Uninstall
```

## Performance Considerations

### Database Indexes
Consider adding indexes for frequent queries:

```sql
-- Index on tinted products for faster filtering
CREATE INDEX idx_product_template_is_tinted 
ON product_template(is_tinted_product) 
WHERE is_tinted_product = TRUE;

-- Index on colorants
CREATE INDEX idx_product_template_is_colorant 
ON product_template(is_colorant) 
WHERE is_colorant = TRUE;

-- Index on tinting BOMs
CREATE INDEX idx_mrp_bom_is_tinting 
ON mrp_bom(is_tinting_bom) 
WHERE is_tinting_bom = TRUE;
```

### Monitoring
Monitor these metrics:
- Wizard load time (should be < 2 seconds)
- Product creation time (should be < 3 seconds)
- BOM creation time (should be < 2 seconds)
- MO creation time (should be < 2 seconds)

## Support & Maintenance

### Log Files
Check these logs for issues:
```
C:\Program Files\Odoo 18\server\odoo.log
```

### Enable Debug Mode
For troubleshooting:
```
Settings > Activate Developer Mode
Settings > Activate Developer Mode (with assets)
```

### Useful SQL Queries
```sql
-- Count tinted products created
SELECT COUNT(*) FROM product_template WHERE is_tinted_product = TRUE;

-- Recent tinting BOMs
SELECT * FROM mrp_bom WHERE is_tinting_bom = TRUE ORDER BY create_date DESC LIMIT 10;

-- Recent tinted MOs
SELECT mp.* 
FROM mrp_production mp
JOIN mrp_bom mb ON mp.bom_id = mb.id
WHERE mb.is_tinting_bom = TRUE
ORDER BY mp.create_date DESC
LIMIT 10;
```

## Contact

For technical support:
- **Developer**: ATIQ
- **System**: odoo.mzaramopaintsandwallpaper.com
- **Company**: Crown Kenya PLC
