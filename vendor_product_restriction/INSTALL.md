# Installation & Configuration Guide

## Quick Start (5 Minutes)

### 1. Install Module

```bash
# Copy module to addons directory
cp -r vendor_product_restriction /path/to/odoo/addons/

# Restart Odoo
sudo systemctl restart odoo

# Or if running manually
./odoo-bin -d your_database -u all
```

**Via Odoo UI:**
1. Go to Apps → Update Apps List
2. Remove "Apps" filter
3. Search: "Vendor Product Restriction"
4. Click "Install"

---

### 2. Verify Installation

**Check Security Group Created:**
```
Settings → Users & Companies → Groups
Search: "Purchase: Vendor Restriction Override"
```

**Verify Admin Has Override:**
```
Settings → Users → Administrator
Access Rights tab → Purchase section
✓ Purchase: Vendor Restriction Override (should be checked)
```

---

### 3. Configure First Product-Vendor Mapping

**Example: Office Chair**

```
Navigate: Products → Products → Office Chair
Click: Purchase Tab

In "Vendors" section:
┌────────────────────────────────────────────┐
│ Vendor         | Price   | Lead | Min Qty │
├────────────────────────────────────────────┤
│ Furniture Co.  | $299.00 | 7d   | 5       │
│ Office Supply  | $315.00 | 5d   | 1       │
└────────────────────────────────────────────┘

Save Product
```

---

### 4. Test with Restricted User

**Create Test User:**
```
Settings → Users → Create

Name: Test Buyer
Email: test.buyer@company.com
Access Rights:
  ✓ Purchase: User (basic purchase rights)
  ✗ Purchase: Vendor Restriction Override (DO NOT CHECK)

Save
```

**Login as Test User and Create RFQ:**
```
Purchase → Orders → Create

1. Select Vendor: "Furniture Co."
2. Add Product Line
3. Product Dropdown: Only shows products mapped to Furniture Co.
4. Try selecting unmapped product: Warning appears with alternatives
```

---

## Detailed Configuration

### Managing User Permissions

#### Grant Override Permission (Unrestricted Access)

**For Purchase Managers:**
```
Settings → Users → [Select Manager]
Access Rights tab
Purchase section:
  ✓ Purchase: Administrator
  ✓ Purchase: Vendor Restriction Override (auto-checked)
```

**For Specific Users:**
```
Settings → Users → [Select User]
Access Rights tab
Purchase section:
  ✓ Purchase: User
  ✓ Purchase: Vendor Restriction Override (manually check)
```

#### Revoke Override Permission

```
Settings → Users → [Select User]
Access Rights tab
Purchase section:
  ✗ Purchase: Vendor Restriction Override (uncheck)
```

---

### Configuring Product-Vendor Mappings

#### Method 1: Via Product Form

```
Products → [Select Product] → Purchase Tab

Add Vendor Line:
- Vendor: [Select supplier from dropdown]
- Vendor Product Name: [Optional alternate name]
- Vendor Product Code: [Optional SKU/code]
- Price: [Unit price from vendor]
- Min. Quantity: [Minimum order quantity]
- Delivery Lead Time: [Days to delivery]

Save
```

#### Method 2: Via Import

```csv
product_tmpl_id/id,partner_id/id,price,delay,min_qty
product.product_template_1,base.res_partner_1,299.00,7,5
product.product_template_1,base.res_partner_2,315.00,5,1
```

Import via: Products → Import (with product.supplierinfo model)

#### Method 3: Bulk Edit

```
Products → Products → List View
Select multiple products
Action → Set Vendor Information (custom action if added)
```

---

### Visual Indicators

The module adds helpful UI elements:

#### For Restricted Users:
```
┌─────────────────────────────────────────────────┐
│ ℹ️ Product Filtering Active                    │
│ Products will be filtered based on vendor       │
└─────────────────────────────────────────────────┘
```

#### For Override Users:
```
┌─────────────────────────────────────────────────┐
│ ✓ Override Active                               │
│ You can select any purchasable product          │
└─────────────────────────────────────────────────┘
```

---

## Advanced Configuration

### Customize When No Vendor Selected

**Default Behavior:** Shows all products when no vendor is selected

**To Restrict When No Vendor:**

Edit: `models/purchase_order.py`, line ~19

```python
# Change this:
if not self.partner_id:
    return {
        'domain': {
            'order_line': {
                'product_id': [('purchase_ok', '=', True)]
            }
        }
    }

# To this (for restricted users only):
if not self.partner_id:
    has_override = self.env.user.has_group(
        'vendor_product_restriction.group_vendor_restriction_override'
    )
    if has_override:
        domain = [('purchase_ok', '=', True)]
    else:
        domain = [('id', '=', False)]  # Show nothing
    
    return {
        'domain': {
            'order_line': {
                'product_id': domain
            }
        }
    }
```

### Add Additional Filtering Criteria

**Example: Filter by Product Category**

Edit: `models/purchase_order.py`, line ~50

```python
if has_override:
    domain = [('purchase_ok', '=', True)]
else:
    domain = [
        ('purchase_ok', '=', True),
        ('seller_ids.partner_id', '=', self.partner_id.id),
        ('categ_id', 'in', [1, 2, 3]),  # Add category filter
    ]
```

**Example: Filter by Stock Availability**

```python
domain.append(('qty_available', '>', 0))
```

### Customize Warning Messages

Edit: `models/purchase_order.py`, line ~100

```python
warning_message = _(
    "Custom Warning Title\n\n"
    "Your message: {product_name} not available from {vendor_name}\n\n"
    "Custom suggestions..."
).format(
    product_name=product.display_name,
    vendor_name=selected_vendor.name
)
```

---

## Integration with Existing Modules

### With `purchase_net_price_compute`

**No additional configuration needed.**

Order of operations:
1. Vendor selected → Product filtering applied ✓
2. Product selected → Pricing rule lookup ✓
3. Discount/freight applied → Net price calculated ✓
4. Custom pricing flows normally ✓

### With `vendor_price_check`

**No additional configuration needed.**

Wizard workflow:
1. Create filtered RFQ → Confirm to PO ✓
2. Open vendor price wizard ✓
3. All products visible in wizard (filtering only applies to RFQ creation) ✓
4. Enter vendor prices → Bill created ✓

---

## Troubleshooting

### Problem: Module Won't Install

**Symptom:** Error during installation

**Check:**
```bash
# Check Odoo logs
tail -f /var/log/odoo/odoo-server.log

# Verify dependencies
- purchase module installed?
- purchase_stock module installed?
```

**Solution:**
```bash
# Update module list
./odoo-bin -d database -u all

# Force upgrade
./odoo-bin -d database -u vendor_product_restriction --stop-after-init
```

---

### Problem: Security Group Not Appearing

**Symptom:** Can't find "Vendor Restriction Override" group

**Check:**
```sql
-- Check if group was created
SELECT name, category_id FROM res_groups 
WHERE name LIKE '%Vendor Restriction%';
```

**Solution:**
```bash
# Reinstall module
./odoo-bin -d database -u vendor_product_restriction --stop-after-init

# Or via UI: Apps → [Find Module] → Upgrade
```

---

### Problem: All Users Have Override

**Symptom:** Filtering not working for any user

**Check:**
```
Settings → Users → [Each User]
Access Rights → Purchase section
```

**Solution:**
```
Manually remove override from users who should be restricted:
1. Go to user record
2. Access Rights tab
3. Uncheck: "Purchase: Vendor Restriction Override"
4. Save
5. User logs out and back in
```

---

### Problem: Products Not Filtering

**Symptom:** Restricted users see all products

**Diagnostic Steps:**
```python
# Enable debug mode
Settings → Activate Developer Mode

# Check user groups
from terminal: 
./odoo-bin shell -d database
>>> user = env['res.users'].browse(USER_ID)
>>> user.has_group('vendor_product_restriction.group_vendor_restriction_override')

# Should return False for restricted users
```

**Check:**
1. Is user in override group? (Should be NO)
2. Are products marked "Can be Purchased"?
3. Are vendor mappings active?
4. Is onchange firing? (Check browser console)

---

### Problem: Warning Not Showing

**Symptom:** No warning when selecting unmapped product

**Possible Causes:**
1. User has override group (warnings disabled for override users)
2. Product actually IS mapped (check Product → Purchase → Vendors)
3. JavaScript error preventing onchange (check browser console)

**Solution:**
```javascript
// Check browser console for errors
F12 → Console tab

// Should see no errors when selecting product
// If errors appear, check Odoo logs
```

---

## Performance Considerations

### For Large Product Catalogs (10,000+ products)

**Add Database Index:**
```sql
CREATE INDEX idx_product_supplierinfo_partner 
ON product_supplierinfo(partner_id);

CREATE INDEX idx_product_supplierinfo_product_tmpl 
ON product_supplierinfo(product_tmpl_id);
```

**Monitor Query Performance:**
```sql
-- Check slow queries
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
WHERE query LIKE '%seller_ids%'
ORDER BY mean_time DESC;
```

### For Many Users (100+ concurrent)

**Enable Caching:**
- Group membership checks are already cached by Odoo
- No additional configuration needed

**Monitor Server Load:**
```bash
# Watch CPU during RFQ creation
top -u odoo

# Should show minimal impact from filtering
```

---

## Uninstallation

### Clean Uninstall

```
Apps → Vendor Product Restriction → Uninstall

Confirms:
✓ Security group removed
✓ View inheritance removed
✓ Model extensions removed
✓ No data loss (vendor mappings preserved)
```

### Data Preservation

**What's Kept:**
- All vendor-product mappings (product.supplierinfo)
- All existing RFQs and POs
- All user permissions (except override group)

**What's Removed:**
- Security group "Vendor Restriction Override"
- UI badges and indicators
- Filtering logic

---

## Next Steps

1. ✓ Install module
2. ✓ Configure 5-10 test products with vendor mappings
3. ✓ Create restricted test user
4. ✓ Test RFQ creation workflow
5. ✓ Train end users
6. ✓ Roll out to production

---

## Support Contacts

**Technical Issues:**
- Check: README.md
- Logs: /var/log/odoo/odoo-server.log
- Debug: Activate Developer Mode

**Configuration Help:**
- User Guide: See README.md
- Odoo Docs: https://www.odoo.com/documentation

**Custom Development:**
- Contact: your.company@example.com
- Module customization available
