# Vendor Product Restriction with Override

## Overview

This module implements vendor-based product filtering on Request for Quotations (RFQs) and Purchase Orders with a permission-based override mechanism.

### Key Features

✅ **Dynamic Product Filtering**
- Restricts product selection based on vendor-product mapping
- Products must be configured in Product → Purchase → Vendors section
- Real-time filtering when vendor is selected or changed

✅ **Security Group Override**
- Security group: "Purchase: Vendor Restriction Override"
- Automatically assigned to Administrators and Purchase Managers
- Override users can select any purchasable product

✅ **Enhanced User Experience**
- Clear warning messages when unmapped products are selected
- Shows alternative vendors with pricing information
- Helpful guidance for resolving mapping issues
- Visual indicators for filtered vs. unrestricted modes

✅ **Seamless Integration**
- Compatible with `purchase_net_price_compute` module
- Works with `vendor_price_check` wizard workflow
- Preserves all standard Odoo purchase functionality
- No conflicts with custom pricing logic

---

## Installation

### Prerequisites

- Odoo 17.0 or later (tested on Odoo 18)
- `purchase` module installed
- `purchase_stock` module installed

### Installation Steps

1. **Copy Module to Addons**
   ```bash
   cp -r vendor_product_restriction /path/to/odoo/addons/
   ```

2. **Update Apps List**
   - Navigate to: Apps → Update Apps List
   - Search for "Vendor Product Restriction"

3. **Install Module**
   - Click Install button
   - Module will automatically:
     - Create security group
     - Assign override permission to admins
     - Extend purchase order views
     - Apply filtering logic

4. **Verify Installation**
   - Go to: Settings → Users & Companies → Groups
   - Search for: "Purchase: Vendor Restriction Override"
   - Confirm administrators are assigned

---

## Configuration

### 1. Configure Vendor-Product Mappings

**For each product that should be available for purchase:**

1. Navigate to: **Products → Products → [Select Product]**
2. Go to: **Purchase Tab**
3. In **Vendors** section, click **Add a line**
4. Configure:
   - **Vendor**: Select supplier
   - **Price**: Unit price from vendor
   - **Delivery Lead Time**: Days to delivery
   - **Min. Quantity**: Minimum order quantity
5. Save the product

**Example Configuration:**

```
Product: Office Chair Deluxe
└── Purchase Tab
    └── Vendors:
        ├── Vendor A - Furniture Direct
        │   ├── Price: $299.00
        │   ├── Lead Time: 7 days
        │   └── Min Qty: 5
        └── Vendor B - Office Supplies Inc
            ├── Price: $315.00
            ├── Lead Time: 5 days
            └── Min Qty: 1
```

### 2. Assign User Permissions

**Grant Override Permission (Unrestricted Access):**

1. Go to: **Settings → Users & Companies → Users**
2. Select user (e.g., Purchase Manager)
3. Go to: **Access Rights** tab
4. Find: **Purchase** section
5. Enable: **Purchase: Vendor Restriction Override**
6. Save

**By Default:**
- ✅ Administrators: Have override (unrestricted)
- ✅ Purchase Managers: Have override (unrestricted)
- ❌ Purchase Users: Restricted to vendor mappings

### 3. Optional: Modify Default Behavior

**To restrict products when NO vendor is selected:**

Edit `models/purchase_order.py`, line ~25:

```python
# Current: Shows all products when no vendor selected
if not self.partner_id:
    return {
        'domain': {
            'order_line': {
                'product_id': [('purchase_ok', '=', True)]
            }
        }
    }

# Change to: Show NO products when no vendor selected (for restricted users)
if not self.partner_id:
    has_override = self.env.user.has_group(
        'vendor_product_restriction.group_vendor_restriction_override'
    )
    if has_override:
        return {'domain': {'order_line': {'product_id': [('purchase_ok', '=', True)]}}}
    else:
        return {'domain': {'order_line': {'product_id': [('id', '=', False)]}}}
```

---

## Usage Guide

### For Restricted Users (Standard Purchase Users)

#### Creating an RFQ:

1. **Navigate**: Purchase → Orders → Create
2. **Select Vendor**: Choose supplier from dropdown
3. **Add Products**: Click "Add a product" on order lines
4. **Available Products**: Only products mapped to selected vendor appear
5. **Complete Order**: Fill remaining fields and confirm

#### If Product Not Found:

**You'll see a warning message:**

```
⚠️ Vendor Restriction

Product Not Available for Selected Vendor

The product 'Office Chair Deluxe' exists in inventory but is not 
configured for vendor 'ABC Supplies'.

This product IS available from the following vendors:
  • Furniture Direct
    Price: $299.00 | Lead Time: 7 days
  • Office Supplies Inc
    Price: $315.00 | Lead Time: 5 days

Actions you can take:
✓ Change the vendor to one of the suppliers listed above
✓ Contact your administrator to add 'ABC Supplies' as a supplier 
  for this product in the Product's Purchase tab
✓ Choose a different product from the available list for this vendor
```

**Next Steps:**
- Option A: Change vendor to one that supplies the product
- Option B: Select different product from available list
- Option C: Request admin to add vendor mapping

### For Override Users (Managers/Admins)

#### Creating an RFQ:

1. **Navigate**: Purchase → Orders → Create
2. **Visual Indicator**: Green badge shows "Override Active"
3. **Select Vendor**: Choose any supplier
4. **Add Products**: Click "Add a product" on order lines
5. **Available Products**: ALL purchasable products visible
6. **No Restrictions**: Can select any product regardless of mapping

**Use Cases for Override:**
- Emergency purchases from new vendors
- Onboarding new vendor relationships
- Special procurement scenarios
- Cross-vendor price negotiations
- One-time purchases

---

## Integration with Existing Modules

### Compatible with `purchase_net_price_compute`

This module works seamlessly with custom pricing calculations:

```python
# Order of operations:
1. Vendor selected → Product filtering applied
2. Product selected → Pricing rule computed
3. Applied discount/freight calculated from rules
4. Net price computed with discounts and freight
5. Totals calculated including taxes
```

**No conflicts** - filtering happens before pricing logic.

### Compatible with `vendor_price_check`

The vendor bill wizard continues to work normally:

```python
# Workflow:
1. Create RFQ with vendor-filtered products
2. Confirm RFQ → becomes Purchase Order
3. Click "Create Bill" → Opens vendor price wizard
4. Enter vendor bill prices → Net prices calculated
5. Confirm wizard → Bill created with correct amounts
```

**The wizard sees all products on the PO** - filtering only applies during RFQ creation.

---

## Testing Scenarios

### Test 1: Restricted User - Mapped Product

```
Given: User WITHOUT override group
  And: Vendor A is selected
  And: Product "Chair" is mapped to Vendor A
When: User selects Product "Chair"
Then: Product is added successfully
  And: No warnings appear
  And: Pricing rules apply normally
```

### Test 2: Restricted User - Unmapped Product

```
Given: User WITHOUT override group
  And: Vendor A is selected
  And: Product "Desk" is mapped ONLY to Vendor B
When: User attempts to select Product "Desk"
Then: Warning appears showing:
  - Product name
  - Current vendor (A)
  - Alternative vendors (B)
  - Suggested actions
  And: Product selection is cleared
  And: User must change vendor or choose different product
```

### Test 3: Restricted User - No Vendor Mappings

```
Given: User WITHOUT override group
  And: Vendor A is selected
  And: Product "Lamp" has NO vendor mappings
When: User attempts to select Product "Lamp"
Then: Warning appears: "Product Not Configured for Purchase"
  And: Message suggests contacting administrator
  And: Product selection is cleared
```

### Test 4: Override User - Any Product

```
Given: User WITH override group (admin/manager)
  And: ANY vendor is selected (or none)
  And: Any product exists
When: User selects any product
Then: Product is added successfully
  And: No restrictions apply
  And: Green "Override Active" badge visible
  And: All purchasable products appear in dropdown
```

### Test 5: Vendor Change Mid-Order

```
Given: Restricted user has selected products for Vendor A
When: User changes vendor to Vendor B
Then: Product dropdown updates immediately
  And: New lines only show Vendor B products
  And: Existing lines remain unchanged (not retroactive)
```

---

## Troubleshooting

### Problem: All Products Visible for Restricted Users

**Diagnosis:**
- User may have override group assigned accidentally

**Solution:**
1. Go to: Settings → Users → [Select User]
2. Access Rights tab → Purchase section
3. Disable: "Purchase: Vendor Restriction Override"
4. Save and test again

### Problem: Warning Not Appearing

**Diagnosis:**
- onchange method not triggering
- Product selected before vendor

**Solution:**
1. Always select vendor FIRST
2. Then select products
3. If issue persists, check server logs for errors

### Problem: Products Not Appearing Even When Mapped

**Diagnosis:**
- Vendor mapping inactive
- Product not marked as "Can be Purchased"

**Solution:**
1. Go to: Products → [Select Product]
2. Check: "Can be Purchased" is enabled
3. Purchase tab → Vendors → Ensure vendor is active
4. Save and retry

### Problem: Performance Issues with Large Catalogs

**Diagnosis:**
- Filtering domain may be slow on large datasets

**Solution:**
1. Add database index on `product_supplierinfo.partner_id`
2. Optimize seller_ids queries
3. Consider caching frequently-used vendor-product combinations

---

## Technical Details

### Domain Filtering Logic

```python
# For restricted users:
domain = [
    ('purchase_ok', '=', True),              # Must be purchasable
    ('seller_ids.partner_id', '=', vendor_id)  # Vendor in sellers
]

# For override users:
domain = [('purchase_ok', '=', True)]  # Only purchasable check
```

### Group Check Method

```python
has_override = self.env.user.has_group(
    'vendor_product_restriction.group_vendor_restriction_override'
)
# Returns: Boolean (True/False)
# Cached: Yes, for performance
# Evaluated: On every onchange event
```

### Warning Message Structure

```python
return {
    'warning': {
        'title': 'Warning Title',
        'message': 'Detailed explanation with suggestions'
    },
    'value': {
        'product_id': False  # Clear invalid selection
    }
}
```

---

## Customization

### Add Custom Domain Logic

Edit `models/purchase_order.py`:

```python
def _get_product_domain_for_vendor(self, vendor_id):
    """Add custom filtering logic here"""
    domain = super()._get_product_domain_for_vendor(vendor_id)
    
    # Example: Only show products in stock
    domain.append(('qty_available', '>', 0))
    
    # Example: Filter by product category
    domain.append(('categ_id', 'in', [1, 2, 3]))
    
    return domain
```

### Modify Warning Messages

Edit `models/purchase_order.py`, line ~95:

```python
warning_message = _(
    "Your custom message here\n"
    "Product: {product_name}\n"
    "Vendor: {vendor_name}"
).format(
    product_name=product.display_name,
    vendor_name=selected_vendor.name
)
```

### Add Logging

```python
_logger.info(f"User {self.env.user.name} selected product {product.name}")
_logger.warning(f"Unmapped product selection attempted")
```

---

## Security Considerations

### Access Control

- Module uses Odoo's standard security group system
- No custom access rights (ir.model.access) needed
- Inherits from `purchase.group_purchase_user`

### Data Integrity

- UI-level filtering (not database constraints)
- API/import can bypass restrictions (intentional)
- Server-side validation can be added if needed

### Audit Trail

- All warnings logged to server logs
- User actions tracked via standard Odoo logging
- Can add custom audit log if compliance required

---

## Support

### Documentation

- Odoo Purchase Module: https://www.odoo.com/documentation/17.0/applications/inventory_and_mrp/purchase.html
- Product Vendor Info: https://www.odoo.com/documentation/17.0/developer/reference/backend/orm.html

### Common Questions

**Q: Can I disable this module temporarily?**
A: Yes, just uninstall the module. Vendor mappings remain intact.

**Q: Does this affect existing RFQs?**
A: No, only applies to NEW lines added after installation.

**Q: Can I have different restrictions per user?**
A: Yes, assign/remove the override group per user as needed.

**Q: Does this work with multi-company?**
A: Yes, filtering respects company context automatically.

---

## License

LGPL-3

---

## Credits

**Author**: Your Company  
**Maintainer**: Your Company  
**Version**: 17.0.1.0.0  
**Compatible**: Odoo 17.0, 18.0
