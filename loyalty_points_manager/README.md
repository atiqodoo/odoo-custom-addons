# Loyalty Points Manager

A comprehensive Odoo 18 Enterprise module for manual management of customer loyalty points with full accounting integration.

## Features

### 🎯 Core Functionality
- **Manual Points Management**: Add or reduce loyalty points for customers through an intuitive wizard interface
- **Real-time Balance Calculation**: Automatically displays current balance and calculates new balance based on operations
- **Customer Search**: Easy customer lookup with domain filtering for active customers only
- **Operation Types**: Support for both adding and reducing points
- **Validation**: Built-in validation to prevent negative balances and invalid operations

### 📊 Accounting Integration
- **Full Accounting Compliance**: Creates journal entries following accounting standards
- **Configurable Accounts**: Set up debit and credit accounts for loyalty point transactions
- **Monetary Value Tracking**: Assign monetary values to loyalty points for accurate financial reporting
- **Automatic Journal Entry Creation**: Journal entries are created and posted automatically upon confirmation
- **Proper Account Movement**:
  - **Add Points**: Debit Loyalty Expense/Asset → Credit Loyalty Liability
  - **Reduce Points**: Debit Loyalty Liability → Credit Loyalty Expense/Asset

### 🔍 Audit Trail & Tracking
- **Complete History**: Full audit trail of all point adjustments
- **Change Tracking**: Tracks balance before and after adjustments
- **User Attribution**: Records who made each adjustment
- **Reason Required**: Mandatory reason field for accountability
- **Status Management**: Draft, Confirmed, and Cancelled states
- **Chatter Integration**: Activity tracking and messaging

### 🎨 Modern UI/UX (Odoo 18 Compliant)
- Uses `<list>` instead of deprecated `<tree>` tags
- No deprecated `<attribute>` tags
- Clean, intuitive wizard interface
- Color-coded status indicators
- Responsive design
- Smart buttons for quick access to related records

## Installation

### Prerequisites
- Odoo 18 Enterprise
- Required modules: `base`, `contacts`, `loyalty`, `account`

### Installation Steps

1. **Copy the module to your Odoo addons directory**:
   ```bash
   cp -r loyalty_points_manager /path/to/odoo/addons/
   ```

2. **Update the apps list**:
   - Navigate to Apps menu
   - Click "Update Apps List"
   - Search for "Loyalty Points Manager"

3. **Install the module**:
   - Click Install on the module card

## Configuration

### 1. Set Up Loyalty Program
Ensure you have a loyalty program configured:
- Go to **Sales → Configuration → Loyalty Programs**
- Create or verify existing loyalty program

### 2. Configure Accounting (Optional but Recommended)

#### Create Chart of Accounts
Set up the following accounts if not already present:

**Loyalty Points Expense/Asset Account**:
- Account Type: Expenses or Current Assets
- Code: e.g., 6XXX or 1XXX
- Name: "Loyalty Points Expense" or "Loyalty Points Asset"

**Loyalty Points Liability Account**:
- Account Type: Current Liabilities
- Code: e.g., 2XXX
- Name: "Customer Loyalty Points Obligation"

#### Create Journal
- Go to **Accounting → Configuration → Journals**
- Create a new journal or use existing "Miscellaneous Operations"
- Type: General

### 3. Configure System Parameters (Optional)
You can set default accounts in the wizard for easier use

## Usage

### Method 1: Using the Wizard (Recommended)

1. **Open the Wizard**:
   - Go to **Sales → Loyalty → Manage Points**
   - Or from a customer form view, use the action menu

2. **Fill in the Details**:
   - **Customer**: Search and select the customer
   - **Current Balance**: Automatically displays current points (read-only)
   - **Operation Type**: Select "Add Points" or "Reduce Points"
   - **Points Amount**: Enter the number of points to add/reduce
   - **New Balance**: Automatically calculated (read-only)
   - **Reason**: Enter the reason for this adjustment (required)

3. **Accounting Information** (Optional):
   - Click on "Accounting Information" tab
   - **Journal**: Select the journal for the entry
   - **Monetary Value**: Enter the monetary value of points
   - **Debit Account**: Select the debit account
   - **Credit Account**: Select the credit account

4. **Apply the Adjustment**:
   - Click "Apply" button
   - The adjustment is created and confirmed automatically
   - A journal entry is created if accounting fields were filled

### Method 2: Direct Adjustment Creation

1. **Navigate to Adjustments**:
   - Go to **Sales → Loyalty → Points Adjustments**

2. **Create New**:
   - Click "Create" button
   - Fill in all required fields
   - Click "Confirm" to apply the adjustment

## Workflow States

### Draft
- Initial state when adjustment is created
- All fields can be edited
- No impact on customer points or accounting

### Confirmed
- Points are applied to customer loyalty card
- Journal entry is created and posted (if configured)
- Record becomes read-only
- Changes are logged in chatter

### Cancelled
- Reverses the point adjustment
- Cancels the journal entry
- Can be reset to draft if not confirmed

## Accounting Examples

### Example 1: Adding Points

**Scenario**: Add 100 points worth $50 to customer

**Accounting Entry**:
```
Debit:  Loyalty Points Expense    $50.00
Credit: Loyalty Liability          $50.00
```

### Example 2: Reducing Points

**Scenario**: Reduce 50 points worth $25 from customer (redemption)

**Accounting Entry**:
```
Debit:  Loyalty Liability          $25.00
Credit: Loyalty Points Expense     $25.00
```

## Security & Access Rights

### Access Levels

**Users (Sales/User)**:
- Can view, create, and edit adjustments
- Cannot delete confirmed adjustments

**Managers (Sales Manager)**:
- Full access to all operations
- Can delete adjustments (if not confirmed)

**Wizards**:
- All users with base access can use the wizard

## Best Practices

1. **Always Provide Reasons**: Document why points are being adjusted
2. **Use Accounting Integration**: Enable for proper financial tracking
3. **Regular Reconciliation**: Reconcile loyalty point accounts regularly
4. **Review Before Confirmation**: Double-check amounts before confirming
5. **Monitor Adjustments**: Review adjustment reports regularly
6. **Set Up Approval Workflow**: Consider adding approval steps for large adjustments

## Technical Details

### Models

**loyalty.points.adjustment**:
- Main model for storing adjustment records
- Inherits `mail.thread` and `mail.activity.mixin`
- Creates journal entries through `account.move`

**loyalty.points.wizard**:
- Transient model for the wizard interface
- Real-time computation of balances
- Validation of operations

### Key Methods

**action_confirm()**: Confirms adjustment and updates loyalty points
**action_cancel()**: Cancels adjustment and reverses changes
**_create_account_move()**: Creates and posts journal entries
**_compute_current_balance()**: Calculates current customer balance
**_compute_new_balance()**: Calculates balance after operation

### Database Tables

- `loyalty_points_adjustment`: Stores all adjustment records
- `loyalty_points_wizard`: Temporary wizard data (not persisted)

## Troubleshooting

### Issue: "No loyalty program found"
**Solution**: Create a loyalty program in Sales → Configuration → Loyalty Programs

### Issue: "Insufficient points"
**Solution**: Check current balance before reducing points

### Issue: Journal entry not created
**Solution**: Ensure all accounting fields are filled:
- Journal
- Debit Account
- Credit Account
- Points Value (must be > 0)

### Issue: Cannot delete adjustment
**Solution**: Only draft adjustments can be deleted. Cancel confirmed adjustments first.

## Compliance & Standards

This module follows:
- **Odoo 18 Standards**: Uses modern view elements (`<list>` instead of `<tree>`)
- **Accounting Standards**: Proper debit/credit entries
- **IFRS Compliance**: Loyalty liabilities are properly recorded
- **Audit Requirements**: Full tracking of all changes
- **Data Integrity**: Validation and constraints prevent errors

## Support & Customization

For customization requests:
1. Fork the module
2. Modify according to your needs
3. Test thoroughly in a development environment
4. Deploy to production

## Version History

- **18.0.1.0.0** (2024-10-30):
  - Initial release
  - Odoo 18 Enterprise compatible
  - Full accounting integration
  - Wizard interface
  - Audit trail

## License

LGPL-3

## Credits

Developed for Odoo 18 Enterprise

---

**Note**: This module requires Odoo 18 Enterprise edition with the Loyalty and Accounting modules installed.
