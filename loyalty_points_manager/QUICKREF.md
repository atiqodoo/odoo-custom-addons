# Quick Reference Guide
## Loyalty Points Manager - Odoo 18 Enterprise

---

## Quick Start (5 Minutes)

### 1. Install Module
```
Apps → Search "Loyalty Points Manager" → Install
```

### 2. Open Wizard
```
Sales → Loyalty → Manage Points
```

### 3. Adjust Points
- Select Customer
- Choose Add/Reduce
- Enter Amount
- Enter Reason
- Click Apply

**Done!** ✅

---

## Common Operations

### Add Points to Customer
1. Open: **Sales → Loyalty → Manage Points**
2. Customer: `[Select customer]`
3. Operation: `Add Points`
4. Amount: `[Enter points]`
5. Reason: `[Why adding]`
6. Click: **Apply**

### Reduce Points from Customer
1. Open: **Sales → Loyalty → Manage Points**
2. Customer: `[Select customer]`
3. Operation: `Reduce Points`
4. Amount: `[Enter points]`
5. Reason: `[Why reducing]`
6. Click: **Apply**

### View Customer Balance
- Open wizard and select customer
- Current Balance displays automatically

### View All Adjustments
```
Sales → Loyalty → Points Adjustments
```

### Filter Adjustments
- My Adjustments
- By Customer
- By Date
- By Status (Draft/Confirmed/Cancelled)

---

## Accounting Quick Setup

### Required Accounts

**Expense/Asset Account**:
```
Code: 6500
Name: Loyalty Points Expense
Type: Expenses
```

**Liability Account**:
```
Code: 2400
Name: Customer Loyalty Points Obligation
Type: Current Liabilities
```

### Using Accounting in Wizard

1. Fill customer and points details
2. Click **Accounting Information** tab
3. Fill:
   - Journal: `[Select]`
   - Monetary Value: `[$ amount]`
   - Debit Account: `Loyalty Points Expense`
   - Credit Account: `Customer Loyalty Points Obligation`
4. Apply

**Result**: Journal entry created automatically!

---

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Apply adjustment | `Alt + Q` |
| Cancel wizard | `Alt + Z` |
| Confirm adjustment | `Alt + Q` |
| Cancel adjustment | `Alt + X` |
| Reset to draft | `Alt + R` |

---

## Status Flow

```
Draft → Confirmed → (Optional: Cancelled)
  ↓         ↓              ↓
 Edit    Locked      Reversed Points
```

- **Draft**: Can edit all fields
- **Confirmed**: Points applied, cannot edit
- **Cancelled**: Points reversed, can delete

---

## Validation Rules

❌ **Will Fail**:
- Points amount ≤ 0
- Empty reason
- Reduce more points than available
- Delete confirmed adjustment

✅ **Will Succeed**:
- Points amount > 0
- Reason provided
- Sufficient points for reduction
- All required fields filled

---

## Common Error Solutions

### "No loyalty program found"
→ Create loyalty program in **Sales → Configuration → Loyalty Programs**

### "Insufficient points"
→ Check current balance, cannot go negative

### "Cannot delete adjustment"
→ Cancel first, then delete

### Journal entry not created
→ Fill ALL accounting fields (Journal, Accounts, Value)

---

## Menu Locations

```
Sales
  └── Loyalty
       ├── Manage Points (Wizard)
       └── Points Adjustments (List)
       
Accounting
  └── Configuration
       └── Chart of Accounts (Setup)
       └── Journals (Setup)
```

---

## Field Reference

### Wizard Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Customer | Many2one | Yes | Customer to adjust |
| Current Balance | Float | Read-only | Current points |
| Operation Type | Selection | Yes | Add/Reduce |
| Points Amount | Float | Yes | How many points |
| New Balance | Float | Read-only | Calculated balance |
| Reason | Text | Yes | Why adjusting |

### Accounting Fields

| Field | Required for Accounting |
|-------|------------------------|
| Journal | ✅ Yes |
| Monetary Value | ✅ Yes (> 0) |
| Debit Account | ✅ Yes |
| Credit Account | ✅ Yes |

---

## Accounting Entry Format

### Adding Points
```
DR: Loyalty Points Expense      $XX.XX
CR: Loyalty Points Liability    $XX.XX
```

### Reducing Points
```
DR: Loyalty Points Liability    $XX.XX
CR: Loyalty Points Expense      $XX.XX
```

---

## Best Practices

### DO ✅
- Always provide clear reasons
- Double-check amounts before applying
- Use accounting integration for auditing
- Review adjustments regularly
- Train users properly

### DON'T ❌
- Skip the reason field
- Delete confirmed adjustments without canceling
- Make adjustments without authorization
- Forget to verify customer balance
- Ignore insufficient points warnings

---

## Security & Access

### Sales User
- Create/Edit adjustments
- View all adjustments
- Cannot delete confirmed

### Sales Manager
- All user permissions
- Delete adjustments
- Access all records

---

## Reporting

### View Adjustments by Customer
```
Points Adjustments → Group By → Customer
```

### View Daily Adjustments
```
Points Adjustments → Filter → Creation Date
```

### Export to Excel
```
Points Adjustments → List View → Export
```

---

## Integration Points

### With Loyalty Module
- Reads/writes `loyalty.card.points`
- Uses existing loyalty programs
- Compatible with standard loyalty features

### With Accounting Module
- Creates `account.move` entries
- Posts journal entries automatically
- Uses company's configured accounts

### With Contacts Module
- Filters customers only
- Links to partner records
- Shows in customer view

---

## Technical Details

### Models
- `loyalty.points.adjustment` - Main model
- `loyalty.points.wizard` - Wizard (transient)

### Views
- Wizard form view
- Adjustment list view (uses `<list>`, not `<tree>`)
- Adjustment form view
- Search view with filters

### Security
- `ir.model.access.csv` - Access rights
- Sales User and Manager groups

---

## File Structure

```
loyalty_points_manager/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── loyalty_points_adjustment.py
├── wizard/
│   ├── __init__.py
│   └── loyalty_points_wizard.py
├── views/
│   ├── loyalty_points_adjustment_views.xml
│   └── loyalty_points_wizard_views.xml
├── security/
│   └── ir.model.access.csv
├── static/
│   └── description/
│       └── index.html
├── README.md
├── INSTALL.md
└── QUICKREF.md (this file)
```

---

## Support Resources

### Documentation
- README.md - Full documentation
- INSTALL.md - Installation guide
- QUICKREF.md - This file

### Odoo Resources
- Odoo Documentation: docs.odoo.com
- Loyalty Module Guide
- Accounting Module Guide

---

## Version Information

- **Module Version**: 18.0.1.0.0
- **Odoo Version**: 18.0 Enterprise
- **License**: LGPL-3
- **Dependencies**: base, contacts, loyalty, account

---

## Troubleshooting Checklist

Before asking for help, check:

- [ ] Module installed and updated
- [ ] Loyalty program exists
- [ ] User has proper access rights
- [ ] Accounting accounts created (if using)
- [ ] Journal configured (if using)
- [ ] All required fields filled
- [ ] No typos in amounts or reasons
- [ ] Sufficient points for reduction

---

**Print this guide and keep it handy! 📄**

For detailed information, see README.md and INSTALL.md
