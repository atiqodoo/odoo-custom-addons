# Installation & Configuration Guide
## Loyalty Points Manager for Odoo 18 Enterprise

---

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Initial Configuration](#initial-configuration)
4. [Account Setup](#account-setup)
5. [Testing the Module](#testing-the-module)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements
- **Odoo Version**: 18.0 Enterprise Edition
- **Database**: PostgreSQL 12 or higher
- **Python**: 3.10 or higher

### Required Odoo Modules
Ensure these modules are installed before installing Loyalty Points Manager:
- ✅ `base` (Base)
- ✅ `contacts` (Contacts)
- ✅ `loyalty` (Loyalty Program)
- ✅ `account` (Accounting)

### User Permissions
- System Administrator access for installation
- Sales Manager access for configuration

---

## Installation

### Step 1: Copy Module Files

**Option A: Manual Copy**
```bash
# Navigate to your Odoo addons directory
cd /path/to/odoo/addons/

# Copy the module
cp -r /path/to/loyalty_points_manager ./

# Set proper permissions
chown -R odoo:odoo loyalty_points_manager
chmod -R 755 loyalty_points_manager
```

**Option B: Using Git**
```bash
cd /path/to/odoo/addons/
git clone <repository-url> loyalty_points_manager
chown -R odoo:odoo loyalty_points_manager
```

### Step 2: Update Apps List

1. Log in to Odoo as Administrator
2. Go to **Apps** menu
3. Click **Update Apps List** button
4. In the confirmation dialog, click **Update**

### Step 3: Install the Module

1. In the **Apps** menu, remove any filters
2. Search for "Loyalty Points Manager"
3. Click the **Install** button on the module card
4. Wait for installation to complete

### Step 4: Verify Installation

Check that the following menu items appear:
- **Sales → Loyalty → Manage Points**
- **Sales → Loyalty → Points Adjustments**

---

## Initial Configuration

### Step 1: Verify Loyalty Program

1. Go to **Sales → Configuration → Loyalty Programs**
2. Verify that at least one loyalty program exists
3. If none exists, create one:
   - Click **Create**
   - Set **Program Type** to "Loyalty Program"
   - Configure point rules and rewards
   - Click **Save**

### Step 2: Set Up Access Rights

1. Go to **Settings → Users & Companies → Users**
2. Select a user
3. Under **Sales** tab, assign appropriate role:
   - **User - Own Documents Only**: Can manage their own adjustments
   - **Administrator**: Full access to all adjustments

---

## Account Setup

### Step 1: Create Loyalty Accounts

#### 1. Loyalty Points Expense Account

1. Go to **Accounting → Configuration → Chart of Accounts**
2. Click **Create**
3. Fill in:
   - **Code**: 6500 (or appropriate expense code)
   - **Account Name**: Loyalty Points Expense
   - **Type**: Expenses
   - **Reconciliation**: Not required
4. Click **Save**

#### 2. Loyalty Points Liability Account

1. Go to **Accounting → Configuration → Chart of Accounts**
2. Click **Create**
3. Fill in:
   - **Code**: 2400 (or appropriate liability code)
   - **Account Name**: Customer Loyalty Points Obligation
   - **Type**: Current Liabilities
   - **Reconciliation**: Not required
4. Click **Save**

### Step 2: Create or Configure Journal

**Option A: Use Existing Journal**
1. Go to **Accounting → Configuration → Journals**
2. Find "Miscellaneous Operations" or similar
3. Note the journal name for later use

**Option B: Create New Journal**
1. Go to **Accounting → Configuration → Journals**
2. Click **Create**
3. Fill in:
   - **Journal Name**: Loyalty Points
   - **Type**: Miscellaneous
   - **Short Code**: LPT
   - **Default Account**: (optional)
4. Click **Save**

### Step 3: Test Accounting Setup

1. Go to **Sales → Loyalty → Manage Points**
2. Create a test adjustment:
   - Select a customer
   - Operation: Add Points
   - Amount: 10 points
   - Go to **Accounting Information** tab
   - Select your configured journal
   - Enter monetary value: 5.00
   - Select Debit Account: Loyalty Points Expense
   - Select Credit Account: Customer Loyalty Points Obligation
3. Click **Apply**
4. Verify the journal entry was created:
   - A button "Journal Entry" should appear
   - Click it to view the accounting entry

---

## Testing the Module

### Test Case 1: Adding Points

1. **Open Wizard**:
   - Go to **Sales → Loyalty → Manage Points**

2. **Fill Details**:
   - Customer: Select any customer
   - Current Balance: (Note the displayed value)
   - Operation Type: Add Points
   - Points Amount: 50
   - New Balance: (Should show current + 50)
   - Reason: "Welcome bonus"

3. **Optional - Add Accounting**:
   - Go to Accounting Information tab
   - Journal: Select configured journal
   - Monetary Value: 25.00
   - Debit Account: Loyalty Points Expense
   - Credit Account: Customer Loyalty Points Obligation

4. **Apply**:
   - Click "Apply" button
   - Verify success message
   - Check the adjustment record opens

5. **Verify**:
   - Check Points Adjustments list
   - Verify customer loyalty balance increased
   - If accounting configured, check journal entry

### Test Case 2: Reducing Points

1. **Open Wizard**:
   - Go to **Sales → Loyalty → Manage Points**

2. **Fill Details**:
   - Customer: Select same customer from Test Case 1
   - Current Balance: (Should show 50 if Test Case 1 passed)
   - Operation Type: Reduce Points
   - Points Amount: 20
   - New Balance: (Should show 30)
   - Reason: "Point redemption"

3. **Apply and Verify**:
   - Click "Apply"
   - Verify new balance is 30
   - Check adjustment record

### Test Case 3: Validation Testing

**Test Insufficient Points**:
1. Try to reduce more points than available
2. Should get error: "Insufficient points!"

**Test Negative Amount**:
1. Enter -10 in Points Amount
2. Should get error: "Points amount must be greater than zero"

**Test Missing Reason**:
1. Leave Reason field empty
2. Try to apply
3. Should get validation error

---

## Troubleshooting

### Issue: Module Not Appearing in Apps List

**Cause**: Module not in addons path or apps list not updated

**Solution**:
```bash
# Verify module location
ls -la /path/to/odoo/addons/loyalty_points_manager/

# Restart Odoo
sudo systemctl restart odoo

# Update apps list from UI
```

### Issue: "No loyalty program found"

**Cause**: No loyalty program configured

**Solution**:
1. Go to **Sales → Configuration → Loyalty Programs**
2. Create a loyalty program with type "Loyalty Program"

### Issue: Journal Entry Not Created

**Cause**: Missing accounting configuration

**Solution**:
Ensure ALL these fields are filled:
- Journal (required)
- Debit Account (required)
- Credit Account (required)
- Points Value > 0 (required)

### Issue: Access Denied Errors

**Cause**: Insufficient user permissions

**Solution**:
1. Go to **Settings → Users & Companies → Users**
2. Edit the user
3. Under Sales, set to "Administrator"
4. Save and try again

### Issue: Customer Loyalty Balance Not Updating

**Cause**: Adjustment not confirmed

**Solution**:
1. Open the adjustment record
2. Check the status - must be "Confirmed"
3. If "Draft", click the "Confirm" button

### Issue: Cannot Delete Adjustment

**Cause**: Confirmed adjustments cannot be deleted

**Solution**:
1. Click "Cancel" button first
2. Then you can delete if needed
3. Or create a reversing adjustment

---

## Advanced Configuration

### Setting Default Accounts

You can extend the wizard to have default accounts:

```python
# In wizard/loyalty_points_wizard.py
# Add default_get method:

@api.model
def default_get(self, fields):
    res = super(LoyaltyPointsWizard, self).default_get(fields)
    # Get default accounts from company or settings
    company = self.env.company
    res['journal_id'] = # Your default journal ID
    res['debit_account_id'] = # Your default debit account ID
    res['credit_account_id'] = # Your default credit account ID
    return res
```

### Setting Up Automated Workflows

To add approval workflows, install the `approvals` module and extend the model.

---

## Best Practices

1. **Regular Backups**: Always backup before making bulk adjustments
2. **Document Reasons**: Always provide clear, detailed reasons
3. **Test First**: Test in a development/staging environment
4. **Monitor Liability**: Regularly review loyalty points liability account
5. **Audit Reviews**: Periodically review adjustment history
6. **User Training**: Train users on proper usage and when to escalate
7. **Set Limits**: Consider implementing approval for large adjustments

---

## Need Help?

If you encounter issues not covered here:

1. Check the README.md file for additional documentation
2. Review Odoo logs: `/var/log/odoo/odoo-server.log`
3. Enable debug mode in Odoo for detailed error messages
4. Check database logs for SQL errors

---

## Next Steps

After successful installation:

1. ✅ Configure default accounts for common use
2. ✅ Train users on the wizard interface
3. ✅ Set up reporting for loyalty liability
4. ✅ Configure automated reminders for reviews
5. ✅ Customize views if needed for your workflow

---

**Version**: 18.0.1.0.0  
**Last Updated**: October 2024  
**Compatible with**: Odoo 18 Enterprise
