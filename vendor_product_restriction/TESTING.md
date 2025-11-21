# Testing Guide - Vendor Product Restriction

## Test Environment Setup

### Prerequisites

```
✓ Module installed
✓ 2 test vendors created
✓ 5 test products with mixed vendor mappings
✓ 2 test users (1 restricted, 1 override)
```

### Test Data Setup

#### Create Test Vendors

```
Navigate: Contacts → Create

Vendor A - "Furniture Direct"
- Name: Furniture Direct
- Company Type: Company
- Is a Vendor: ✓

Vendor B - "Office Supplies Inc"
- Name: Office Supplies Inc
- Company Type: Company
- Is a Vendor: ✓
```

#### Create Test Products

```
Product 1: "Executive Desk"
└── Purchase Tab → Vendors:
    ├── Furniture Direct: $450.00, 7 days, Min: 1
    └── Office Supplies Inc: $475.00, 5 days, Min: 1

Product 2: "Office Chair"
└── Purchase Tab → Vendors:
    └── Furniture Direct: $299.00, 7 days, Min: 5

Product 3: "Desk Lamp"
└── Purchase Tab → Vendors:
    └── Office Supplies Inc: $45.00, 3 days, Min: 10

Product 4: "Filing Cabinet"
└── Purchase Tab → Vendors:
    └── (NO VENDORS - intentionally blank)

Product 5: "Conference Table"
└── Purchase Tab → Vendors:
    ├── Furniture Direct: $850.00, 14 days, Min: 1
    └── Office Supplies Inc: $900.00, 10 days, Min: 1
```

#### Create Test Users

```
User 1: "Restricted Buyer"
- Login: restricted.buyer
- Access Rights:
  ✓ Purchase: User
  ✗ Purchase: Vendor Restriction Override

User 2: "Override Manager"
- Login: override.manager
- Access Rights:
  ✓ Purchase: Administrator
  ✓ Purchase: Vendor Restriction Override (auto-assigned)
```

---

## Test Cases

### Test Suite 1: Restricted User - Basic Filtering

#### TC1.1: Single Vendor Product Selection

**Objective:** Verify restricted user can select product mapped to chosen vendor

**Steps:**
1. Login as: `restricted.buyer`
2. Navigate: Purchase → Orders → Create
3. Select Vendor: "Furniture Direct"
4. Click: Add a product
5. Search: "Office Chair"
6. Select: Office Chair

**Expected Result:**
```
✓ Product appears in search results
✓ Product is added to order line
✓ No warnings appear
✓ Line shows: Office Chair, $299.00
✓ Applied discount/freight from pricing rules (if configured)
```

**Status:** [ ] Pass [ ] Fail

---

#### TC1.2: Multi-Vendor Product Selection

**Objective:** Verify product mapped to multiple vendors appears for all

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Add Product: "Executive Desk"
4. Create another RFQ with Vendor: "Office Supplies Inc"
5. Add Product: "Executive Desk"

**Expected Result:**
```
✓ Executive Desk appears for Furniture Direct
✓ Executive Desk appears for Office Supplies Inc
✓ Prices may differ based on vendor
✓ No warnings for either selection
```

**Status:** [ ] Pass [ ] Fail

---

#### TC1.3: Unmapped Product Warning

**Objective:** Verify warning appears when selecting unmapped product

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Try to select: "Desk Lamp" (only mapped to Office Supplies Inc)

**Expected Result:**
```
✓ Warning popup appears
✓ Title: "⚠️ Vendor Restriction"
✓ Message includes:
  - Product name: "Desk Lamp"
  - Current vendor: "Furniture Direct"
  - Alternative vendor: "Office Supplies Inc"
  - Price from alternative: "$45.00"
  - Suggested actions listed
✓ Product selection is cleared
✓ User can continue with different product or vendor
```

**Warning Message Should Contain:**
```
Product Not Available for Selected Vendor

The product 'Desk Lamp' exists in inventory but is not 
configured for vendor 'Furniture Direct'.

This product IS available from the following vendors:
  • Office Supplies Inc
    Price: $45.00 | Lead Time: 3 days

Actions you can take:
✓ Change the vendor to one of the suppliers listed above
✓ Contact your administrator to add 'Furniture Direct' as a 
  supplier for this product
✓ Choose a different product from the available list
```

**Status:** [ ] Pass [ ] Fail

---

#### TC1.4: Product with No Vendors

**Objective:** Verify warning for product without any vendor mappings

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Try to select: "Filing Cabinet" (no vendors configured)

**Expected Result:**
```
✓ Warning popup appears
✓ Title: "⚠️ Vendor Restriction"
✓ Message states product has no vendor configurations
✓ Suggests contacting administrator
✓ No alternative vendors listed (none exist)
✓ Product selection is cleared
```

**Warning Message Should Contain:**
```
Product Not Configured for Purchase

The product 'Filing Cabinet' exists in inventory but has no 
vendor configurations set up.

Please contact your administrator to:
• Add vendor information on the Product's Purchase tab
• Set up pricing and delivery terms
```

**Status:** [ ] Pass [ ] Fail

---

#### TC1.5: Product Dropdown Filtering

**Objective:** Verify product dropdown only shows mapped products

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Click: Add a product → Product dropdown
4. View all available products

**Expected Result:**
```
Products Shown (Mapped to Furniture Direct):
✓ Executive Desk
✓ Office Chair
✓ Conference Table

Products Hidden (Not Mapped):
✗ Desk Lamp (mapped to Office Supplies Inc)
✗ Filing Cabinet (no vendors)
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 2: Restricted User - Vendor Changes

#### TC2.1: Change Vendor Mid-Order

**Objective:** Verify product filtering updates when vendor changes

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Add Product: "Office Chair"
4. Change Vendor to: "Office Supplies Inc"
5. Try to add new product line

**Expected Result:**
```
✓ Existing line (Office Chair) remains unchanged
✓ Product dropdown for NEW lines shows only Office Supplies Inc products
✓ Desk Lamp now appears
✓ Office Chair no longer appears for NEW lines
✓ Can add Desk Lamp successfully
```

**Status:** [ ] Pass [ ] Fail

---

#### TC2.2: No Vendor Selected

**Objective:** Verify behavior when no vendor is selected

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ WITHOUT selecting vendor
3. Try to add product

**Expected Result (Default Behavior):**
```
✓ All purchasable products appear
✓ No filtering applied yet
✓ Once vendor selected, filtering activates
```

**Alternative Behavior (If Configured to Restrict):**
```
✓ Product dropdown shows no results OR is disabled
✓ Message: "Please select vendor first"
✓ Cannot add products until vendor selected
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 3: Override User - Unrestricted Access

#### TC3.1: Override User Sees All Products

**Objective:** Verify override users bypass filtering completely

**Steps:**
1. Login as: `override.manager`
2. Create RFQ with Vendor: "Furniture Direct"
3. View product dropdown

**Expected Result:**
```
✓ Green badge shows: "Override Active"
✓ ALL purchasable products appear:
  - Executive Desk
  - Office Chair
  - Desk Lamp (even though not mapped to Furniture Direct)
  - Conference Table
  - Filing Cabinet (even with no vendors)
✓ No filtering applied
✓ No warnings when selecting any product
```

**Status:** [ ] Pass [ ] Fail

---

#### TC3.2: Override User Selects Unmapped Product

**Objective:** Verify no warnings for override users

**Steps:**
1. Login as: `override.manager`
2. Create RFQ with Vendor: "Furniture Direct"
3. Select Product: "Desk Lamp" (not mapped to Furniture Direct)

**Expected Result:**
```
✓ Product is added successfully
✓ NO warnings appear
✓ Line shows: Desk Lamp
✓ Pricing may default to last purchase price
✓ Order can be confirmed normally
```

**Status:** [ ] Pass [ ] Fail

---

#### TC3.3: Override User with No Vendor

**Objective:** Verify override users can select products without vendor

**Steps:**
1. Login as: `override.manager`
2. Create RFQ WITHOUT selecting vendor
3. Add product lines

**Expected Result:**
```
✓ Can add products immediately
✓ All purchasable products visible
✓ No vendor selection required
✓ Can save RFQ in draft state
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 4: UI/UX Verification

#### TC4.1: Visual Indicators - Restricted User

**Objective:** Verify UI shows appropriate indicators for restricted users

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ

**Expected Result:**
```
✓ Info badge appears above vendor field:
  "ℹ️ Product Filtering Active"
✓ Badge states products will be filtered
✓ Blue/info color scheme
```

**Status:** [ ] Pass [ ] Fail

---

#### TC4.2: Visual Indicators - Override User

**Objective:** Verify UI shows appropriate indicators for override users

**Steps:**
1. Login as: `override.manager`
2. Create RFQ

**Expected Result:**
```
✓ Success badge appears above vendor field:
  "✓ Override Active"
✓ Badge states user can select any product
✓ Green/success color scheme
```

**Status:** [ ] Pass [ ] Fail

---

#### TC4.3: Warning Message Formatting

**Objective:** Verify warning messages are well-formatted and readable

**Steps:**
1. Login as: `restricted.buyer`
2. Trigger warning by selecting unmapped product
3. Review warning message

**Expected Result:**
```
✓ Clear title with icon (⚠️)
✓ Paragraph spacing for readability
✓ Bold text for emphasis
✓ Bullet points for lists
✓ Alternative vendors clearly listed
✓ Pricing information formatted (e.g., $45.00)
✓ Lead times shown (e.g., 3 days)
✓ Actions section with suggestions
✓ Professional, helpful tone
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 5: Integration Testing

#### TC5.1: Integration with Custom Pricing

**Objective:** Verify compatibility with purchase_net_price_compute

**Prerequisites:**
- `purchase_net_price_compute` module installed
- Pricing rules configured for test products

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Add Product: "Office Chair"
4. Verify pricing calculations

**Expected Result:**
```
✓ Product filtering works
✓ Pricing rule is loaded
✓ Applied discount shows (e.g., 10%)
✓ Applied freight shows (e.g., 5%)
✓ Net price calculated correctly
✓ Line total = (price * qty * (1-discount) * (1+freight))
✓ No conflicts between modules
```

**Status:** [ ] Pass [ ] Fail

---

#### TC5.2: Integration with Vendor Bill Wizard

**Objective:** Verify compatibility with vendor_price_check

**Prerequisites:**
- `vendor_price_check` module installed

**Steps:**
1. Create RFQ with filtered products
2. Confirm RFQ → becomes PO
3. Click: "Create Bill" or vendor bill action
4. Verify wizard opens correctly

**Expected Result:**
```
✓ Wizard opens successfully
✓ All PO lines visible in wizard
✓ Can enter vendor prices for all products
✓ No filtering applied in wizard (filtering only during RFQ creation)
✓ Bill created correctly with entered prices
```

**Status:** [ ] Pass [ ] Fail

---

#### TC5.3: Multi-Line RFQ

**Objective:** Verify filtering works correctly with multiple lines

**Steps:**
1. Login as: `restricted.buyer`
2. Create RFQ with Vendor: "Furniture Direct"
3. Add 3 product lines:
   - Executive Desk
   - Office Chair
   - Conference Table

**Expected Result:**
```
✓ All 3 products added successfully
✓ Each line respects vendor mapping
✓ Totals calculated correctly
✓ Can save and confirm RFQ
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 6: Edge Cases

#### TC6.1: Rapid Vendor Switching

**Objective:** Test performance with rapid vendor changes

**Steps:**
1. Create RFQ
2. Rapidly switch between vendors 5 times
3. Add product after each switch

**Expected Result:**
```
✓ No lag or performance issues
✓ Product dropdown updates immediately
✓ Correct products shown for each vendor
✓ No JavaScript errors in console
```

**Status:** [ ] Pass [ ] Fail

---

#### TC6.2: Product Variant Handling

**Objective:** Verify filtering works with product variants

**Prerequisites:**
- Product with multiple variants
- Variants mapped to different vendors

**Steps:**
1. Create product with 2 variants
2. Map Variant A to Vendor A
3. Map Variant B to Vendor B
4. Test RFQ creation for each vendor

**Expected Result:**
```
✓ Vendor A sees only Variant A
✓ Vendor B sees only Variant B
✓ Variants filtered independently
```

**Status:** [ ] Pass [ ] Fail

---

#### TC6.3: Product Search with Special Characters

**Objective:** Test search functionality with special characters

**Steps:**
1. Create product: "Office Chair (Ergonomic) - Premium"
2. Map to vendor
3. Search for product using partial name

**Expected Result:**
```
✓ Search works with parentheses
✓ Search works with hyphens
✓ Partial search returns correct results
✓ Product can be selected
```

**Status:** [ ] Pass [ ] Fail

---

### Test Suite 7: Performance Testing

#### TC7.1: Large Product Catalog

**Objective:** Test performance with 1000+ products

**Setup:**
- Import 1000 test products
- Map 500 to Vendor A
- Map 500 to Vendor B

**Steps:**
1. Create RFQ with Vendor A
2. Open product dropdown
3. Measure load time

**Expected Result:**
```
✓ Dropdown loads in < 2 seconds
✓ Search is responsive
✓ Filtering applies correctly
✓ No browser lag
```

**Status:** [ ] Pass [ ] Fail

---

#### TC7.2: Concurrent Users

**Objective:** Test with multiple users creating RFQs simultaneously

**Setup:**
- 10 users logged in
- Each creates RFQ at same time

**Steps:**
1. All users create RFQs simultaneously
2. Each selects different vendors
3. Each adds products

**Expected Result:**
```
✓ No conflicts between users
✓ Each user sees correct filtered products
✓ Server response time acceptable
✓ No database locks or errors
```

**Status:** [ ] Pass [ ] Fail

---

## Regression Testing

### After Module Update

Run complete test suite to verify:
```
[ ] All TC1 tests pass (Restricted User - Basic)
[ ] All TC2 tests pass (Restricted User - Vendor Changes)
[ ] All TC3 tests pass (Override User)
[ ] All TC4 tests pass (UI/UX)
[ ] All TC5 tests pass (Integration)
[ ] All TC6 tests pass (Edge Cases)
[ ] All TC7 tests pass (Performance)
```

### After Odoo Upgrade

Focus on:
```
[ ] TC1.1-1.5 (Core filtering functionality)
[ ] TC3.1-3.2 (Override permissions)
[ ] TC5.1-5.2 (Module integrations)
```

---

## Test Result Summary

### Test Execution Date: ________________

**Total Test Cases:** 23

**Results:**
- Passed: _____ / 23
- Failed: _____ / 23
- Blocked: _____ / 23
- Not Executed: _____ / 23

**Critical Issues Found:** _____

**Non-Critical Issues Found:** _____

**Tested By:** ________________

**Approval:** ________________

---

## Known Issues

Document any known issues discovered during testing:

```
Issue #1:
- Description:
- Severity: [ ] Critical [ ] High [ ] Medium [ ] Low
- Workaround:
- Status: [ ] Open [ ] In Progress [ ] Resolved

Issue #2:
- Description:
- Severity: [ ] Critical [ ] High [ ] Medium [ ] Low
- Workaround:
- Status: [ ] Open [ ] In Progress [ ] Resolved
```

---

## Automated Testing

### Python Unit Tests (Optional)

```python
# tests/test_vendor_restriction.py
from odoo.tests import TransactionCase

class TestVendorRestriction(TransactionCase):
    
    def setUp(self):
        super().setUp()
        # Setup test data
        
    def test_restricted_user_sees_filtered_products(self):
        """Test TC1.1"""
        # Test implementation
        
    def test_override_user_sees_all_products(self):
        """Test TC3.1"""
        # Test implementation
```

Run tests:
```bash
./odoo-bin -d test_database -i vendor_product_restriction --test-enable --stop-after-init
```

---

## Sign-Off

**QA Lead:** ________________  
**Date:** ________________

**Product Owner:** ________________  
**Date:** ________________

**Approved for Production:** [ ] Yes [ ] No

**Comments:**
```
_______________________________________________________________
_______________________________________________________________
_______________________________________________________________
```
