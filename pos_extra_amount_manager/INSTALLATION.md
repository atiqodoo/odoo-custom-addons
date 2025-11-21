# Installation Guide - POS Extra Amount Manager

## Prerequisites

- Odoo 18.0 Enterprise or Community
- Point of Sale module installed
- Accounting module installed
- Stock Accounting enabled (for AVCO costing)

## Installation Steps

### 1. Upload Module

**Option A: Manual Installation**
```bash
# Copy module to addons directory
cp -r pos_extra_amount_manager /path/to/odoo/addons/

# Or for custom addons path
cp -r pos_extra_amount_manager /path/to/custom_addons/
```

**Option B: Via Odoo Interface**
1. Compress the module folder as ZIP (not this ZIP, but the module folder itself)
2. Go to Apps → Upload
3. Select the ZIP file

### 2. Update Apps List
1. Activate Developer Mode: Settings → Activate Developer Mode
2. Go to Apps → Update Apps List
3. Click "Update" and wait

### 3. Install Module
1. Remove "Apps" filter from search
2. Search for "POS Extra Amount Manager"
3. Click "Install"
4. Wait for installation to complete

## Post-Installation Configuration

### Step 1: Configure Chart of Accounts

Create the following accounts if they don't exist:

**1. Extra Revenue Account**
- Account Type: Income → Other Income
- Code: 4020 (example)
- Name: Extra Revenue - POS

**2. COGS - Product Account**
- Account Type: Expenses → Cost of Revenue
- Code: 5010 (example)
- Name: Cost of Goods Sold - Products

**3. COGS - Commission Account**
- Account Type: Expenses → Cost of Revenue
- Code: 5020 (example)
- Name: Cost of Goods Sold - Commissions

**4. Stock Valuation Account**
- Account Type: Assets → Current Assets
- Code: 1400 (example)
- Name: Stock Valuation
- *Note: Usually already exists in product categories*

### Step 2: Configure Default Accounts

1. Navigate to: **Point of Sale → Configuration → Settings**
2. Scroll to **"Extra Amount Management"** section
3. Set default accounts:
   - Extra Revenue Account
   - COGS - Product Account
   - COGS - Commission Account
   - Stock Valuation Account
4. Click **"Save"**

### Step 3: Configure Product Categories

Ensure your products use AVCO costing:

1. Go to: **Inventory → Configuration → Product Categories**
2. Select your category (e.g., "Paint Products")
3. Set:
   - **Costing Method**: Average Cost (AVCO)
   - **Inventory Valuation**: Automated
   - **Stock Valuation Account**: Your stock valuation account
   - **Stock Journal**: Your stock journal
   - **Stock Input Account**: Configure if needed
   - **Stock Output Account**: Configure if needed
4. Click **"Save"**

### Step 4: Verify Products

Check that products have:
1. **Standard Price** set (for AVCO costing)
2. **Product Type**: Storable Product
3. **Category**: Set to category with AVCO costing

### Step 5: Set Up Payment Journals

Ensure you have payment journals configured:

1. Go to: **Accounting → Configuration → Journals**
2. Verify or create:
   - **Cash** journal (Type: Cash)
   - **M-Pesa** journal (Type: Bank) - if used
   - Other payment methods as needed
3. Each journal must have a **Default Account** set

## Verification

### Test the Installation

1. **Create a Test POS Order** (backend):
   - Go to Point of Sale → Orders → Orders
   - Create a new order
   - Add products with prices above pricelist

2. **Calculate Extra Amount**:
   - Click "Calculate Extra Amount" button
   - Verify totals are calculated correctly

3. **Distribute Amount**:
   - Click "Distribute Amount" button
   - Enter percentage or amount
   - Select payment journal and recipient
   - Click "Create Distribution"

4. **Verify Journal Entries**:
   - Go to distribution record
   - Click "View Journal Entries"
   - Verify 3 entries created correctly

## Troubleshooting Installation

### Module Not Appearing in Apps
- Ensure module is in correct addons path
- Check Odoo logs for errors: `tail -f /var/log/odoo/odoo.log`
- Verify __manifest__.py syntax

### Import Errors
- Check all dependencies are installed
- Verify Python syntax in all .py files
- Restart Odoo service: `sudo service odoo restart`

### Missing Menu Items
- Clear browser cache
- Refresh page (Ctrl + F5)
- Check user access rights (must be POS User or Manager)

### Database Errors
- Upgrade module: Apps → POS Extra Amount Manager → Upgrade
- Check database logs
- Restore from backup if needed

## Upgrading

To upgrade the module:

1. **Backup Database**: Always backup before upgrading!

2. **Update Module Files**:
   ```bash
   # Replace module files
   cp -r pos_extra_amount_manager /path/to/odoo/addons/
   ```

3. **Restart Odoo**:
   ```bash
   sudo service odoo restart
   ```

4. **Upgrade Module**:
   - Go to Apps
   - Search "POS Extra Amount Manager"
   - Click "Upgrade"

## Uninstallation

**Warning**: Uninstalling will remove all distribution records and configurations!

1. **Backup Data**: Export distribution records if needed
2. **Uninstall**:
   - Go to Apps
   - Search "POS Extra Amount Manager"
   - Click "Uninstall"
   - Confirm

## Security & Access Rights

### Default Access
- **POS User**: Can create distributions, view records
- **POS Manager**: Full access including deletion

### Custom Access
To modify access rights:
1. Go to Settings → Users & Companies → Groups
2. Select "POS / User" or "POS / Manager"
3. Edit access rights as needed

## Performance Considerations

### For Large Databases
- Index on `pos_order_id` in `pos_extra_distribution` (already included)
- Regular database vacuum
- Archive old distribution records if needed

### Cron Jobs
No cron jobs required - all processing is on-demand

## Multi-Company Setup

If using multi-company:

1. Configure accounts **per company**
2. Switch company before configuring settings
3. Each company has separate default accounts

## Support Contacts

- Technical Issues: support@yourcompany.com
- Documentation: https://www.yourcompany.com/docs
- Community: https://www.odoo.com/forum

## Checklist

After installation, verify:

- [ ] Module installed successfully
- [ ] Default accounts configured
- [ ] Product categories use AVCO
- [ ] Payment journals configured
- [ ] Test order created and calculated
- [ ] Test distribution created
- [ ] Journal entries posted correctly
- [ ] Menu items visible
- [ ] User access rights working

## Next Steps

1. Read the [README.md](README.md) for usage instructions
2. Configure your specific account codes
3. Train users on the workflow
4. Create documentation for your team
5. Set up regular reconciliation processes

---

**Installation Complete!** 🎉

For usage instructions, see [README.md](README.md)
