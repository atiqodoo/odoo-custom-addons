# Quick Start Guide - 10 Minutes to Production

## ⚡ Fast Track Installation

### Prerequisites Check (1 minute)
```bash
# Verify Odoo is running
curl -I http://localhost:8069

# Check database exists
psql -U odoo -l | grep your_database

# Verify purchase module installed
# Login to Odoo → Apps → Installed → Search "Purchase"
```

---

## 🚀 Installation (3 minutes)

### Step 1: Copy Module
```bash
# Option A: From downloaded zip
unzip vendor_product_restriction.zip
sudo cp -r vendor_product_restriction /opt/odoo/custom-addons/
sudo chown -R odoo:odoo /opt/odoo/custom-addons/vendor_product_restriction

# Option B: Direct copy if already extracted
sudo cp -r vendor_product_restriction /path/to/odoo/addons/
sudo chown -R odoo:odoo /path/to/odoo/addons/vendor_product_restriction
```

### Step 2: Install Module
```bash
# Method 1: Command line (fastest)
sudo systemctl restart odoo
./odoo-bin -d your_database -i vendor_product_restriction --stop-after-init

# Method 2: Web UI
# 1. Login to Odoo as administrator
# 2. Apps → Update Apps List
# 3. Remove "Apps" filter
# 4. Search: "Vendor Product Restriction"
# 5. Click Install button
```

---

## ⚙️ Basic Configuration (3 minutes)

### Step 1: Verify Installation
```
Settings → Users & Companies → Groups
Search: "Purchase: Vendor Restriction Override"
✓ Group should exist
✓ Administrator should be in this group
```

### Step 2: Configure 3 Test Products
```
Products → Products → [Select Product] → Purchase Tab

Product 1: Office Chair
└── Vendors → Add:
    - Furniture Co.: $299.00, 7 days, Min: 5

Product 2: Desk Lamp  
└── Vendors → Add:
    - Office Supply: $45.00, 3 days, Min: 10

Product 3: Filing Cabinet
└── Vendors → Add:
    - Furniture Co.: $199.00, 5 days, Min: 1
    - Office Supply: $215.00, 3 days, Min: 1
```

### Step 3: Create Test User (Optional)
```
Settings → Users → Create

Name: Test Buyer
Login: test.buyer
Access Rights:
  ✓ Purchase: User
  ✗ Purchase: Vendor Restriction Override (UNCHECK)

Save
```

---

## ✅ Verify It Works (3 minutes)

### Test 1: As Administrator (Override User)
```
1. Purchase → Orders → Create
2. Select any vendor
3. Observe: Green "Override Active" badge
4. Add product → See ALL purchasable products
5. Add any product → No warnings
✓ Test passed if all products visible
```

### Test 2: As Restricted User
```
1. Login as test.buyer (or create restricted user)
2. Purchase → Orders → Create
3. Observe: Blue "Product Filtering Active" badge
4. Select Vendor: "Furniture Co."
5. Add product line
6. Product dropdown shows ONLY:
   - Office Chair
   - Filing Cabinet
   (NOT Desk Lamp - that's Office Supply only)
7. Try to type "Desk Lamp" in search
8. Observe: Warning message appears with alternatives
✓ Test passed if filtering works and warning shows
```

---

## 🎯 You're Done!

### What Just Happened?
- ✅ Module installed and configured
- ✅ Security groups created and assigned
- ✅ Product filtering active for restricted users
- ✅ Override permissions working for admins

### Next Steps

**For Production Rollout:**
1. Configure all purchasable products with vendors
2. Assign user permissions appropriately
3. Train users on new workflow
4. Monitor for issues in first week

**For More Details:**
- Full documentation: `README.md`
- Installation guide: `INSTALL.md`
- Testing procedures: `TESTING.md`
- Deployment checklist: `DEPLOYMENT.md`

---

## 🆘 Quick Troubleshooting

### Issue: Module not appearing in Apps list
```bash
# Restart Odoo
sudo systemctl restart odoo

# Update apps list via UI
Apps → Update Apps List

# Force module path recognition
./odoo-bin --addons-path=/path/to/addons --update=all -d database --stop-after-init
```

### Issue: Products not filtering
```
Check:
1. Is user in override group? (Settings → Users → [User] → Access Rights)
2. Are products marked "Can be Purchased"? (Products → [Product] → General Info)
3. Are vendor mappings active? (Products → [Product] → Purchase → Vendors)
```

### Issue: Warning not showing
```
- If user has override group: Warnings disabled (by design)
- If product IS mapped: Warning only shows for unmapped products
- Check browser console (F12) for JavaScript errors
```

---

## 📞 Need Help?

**Documentation:**
- `README.md` - Complete user guide
- `INSTALL.md` - Detailed installation
- `TESTING.md` - Test procedures
- `DEPLOYMENT.md` - Production checklist
- `SUMMARY.md` - Module overview

**Support:**
- Email: support@yourcompany.com
- Docs: https://www.odoo.com/documentation

---

## 🎉 Success Checklist

Mark these off as you complete them:

- [ ] Module installed without errors
- [ ] Security group exists and admin assigned
- [ ] 3+ test products configured with vendors
- [ ] Tested as override user (sees all products)
- [ ] Tested as restricted user (sees filtered products)
- [ ] Warning message displays for unmapped products
- [ ] Ready for production (or next test phase)

---

**Total Time:** ~10 minutes  
**Difficulty:** Easy ⭐  
**Status:** Production Ready ✅

---

*Last Updated: 2025-11-02*
*Module Version: 18.0.1.0.0*
