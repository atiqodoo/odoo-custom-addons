# POS Courier Dispatch Module

## Overview
Complete courier dispatch management system for Odoo 18 Point of Sale. Track items sent to customers via courier with full payment, stock, and accounting integration.

## Features

### Core Functionality
- ✅ Register courier dispatches directly from POS orders
- ✅ Track courier information (name, phone, vehicle, reference)
- ✅ Manage payment responsibility (customer/company/shared)
- ✅ Multi-state workflow (draft → in_transit → delivered → confirmed)
- ✅ Customer delivery confirmation
- ✅ Document and photo attachments

### Stock Management
- ✅ Automatic stock moves (Shop → Courier Transit location)
- ✅ Partial dispatch support
- ✅ Stock tracking throughout delivery lifecycle

### Accounting Integration
- ✅ Company-paid courier fees posted to COGS
- ✅ Configurable payment journal and COGS account
- ✅ Automatic journal entry creation
- ✅ Reversal on cancellation

### Reporting & Analytics
- ✅ Kanban view by status
- ✅ Calendar view for dispatch tracking
- ✅ Pivot/Graph analysis
- ✅ Comprehensive filters and grouping

## Installation

1. Copy the `pos_courier_dispatch` folder to your Odoo addons directory
2. Update the apps list: Settings → Apps → Update Apps List
3. Search for "POS Courier Dispatch"
4. Click Install

## Configuration

### Required Setup

1. **Configure COGS Account** (Required for company-paid fees)
   - Go to: Settings → Point of Sale
   - Scroll to "Courier Dispatch Settings"
   - Set "Courier COGS Account" (expense_direct_cost type)
   - Set "Default Payment Journal"

2. **Stock Location** (Auto-created)
   - Location: Courier Transit
   - Type: Transit Location
   - Purpose: Items in transit with courier

3. **User Access**
   - Assign users to "Courier User" group for basic access
   - Assign managers to "Courier Manager" group for full control

### Optional Setup

1. **Courier Companies** (Master Data)
   - Go to: Point of Sale → Courier Dispatch → Courier Companies
   - Add frequently used courier companies
   - Set default payment journals per company

## Usage Workflow

### 1. Create Courier Dispatch

```
POS Order (Paid) → Click "Dispatch via Courier" button
```

**Wizard Steps:**
1. Fill courier details (name, phone, vehicle, reference)
2. Select payment responsibility
3. If company/shared pays: Enter fee and select journal
4. Review/modify delivery address
5. Confirm dispatch quantities
6. Add documents/instructions
7. Click "Register Dispatch"

**System Actions:**
- Creates dispatch record (COURIER/2025/XXXX)
- Moves stock from Shop to Courier Transit
- Creates journal entry if company pays
- Posts message to chatter

### 2. Track Dispatch

**States:**
- **Draft**: Just created, editable
- **In Transit**: Dispatched to customer (auto after creation)
- **Delivered**: Courier reports delivery
- **Confirmed**: Customer confirms receipt
- **Cancelled**: Dispatch cancelled (reverses stock & accounting)

### 3. Mark as Delivered

**Who:** Courier Manager
**When:** When courier reports delivery
**Action:** Click "Mark as Delivered" button

### 4. Confirm Receipt

**Who:** Courier Manager (after customer confirmation)
**When:** Customer confirms goods received
**Action:** 
- Click "Confirm Receipt" button
- Fill confirmation wizard:
  - Confirmation date
  - Goods condition (OK/Not OK)
  - Upload photos (proof of delivery)
  - Add notes/complaints
- Click "Confirm Receipt"

## Payment Scenarios

### Scenario 1: Customer Pays
- Select "Customer Pays"
- No journal entry created
- Track for reference only

### Scenario 2: Company Pays
- Select "Company Pays"
- Enter courier fee
- Select payment journal
- System creates:
  ```
  Debit: COGS Account (courier fee)
  Credit: Bank/Cash Account (courier fee)
  ```

### Scenario 3: Shared Payment
- Select "Shared Payment"
- Enter total courier fee
- System posts 50% to COGS
- Company portion = courier_fee / 2

## Views & Navigation

### Main Views
- **List View**: All dispatches with filters
- **Kanban View**: Group by status (default)
- **Form View**: Full dispatch details
- **Calendar View**: Dispatches by date
- **Pivot View**: Analysis by period/status
- **Graph View**: Visual analytics

### Smart Buttons
- **POS Order Form**: Shows courier dispatch count
- **Courier Dispatch Form**: Shows stock moves
- **Courier Company Form**: Shows total dispatches

## Security & Access Rights

### Groups

**Courier User** (`group_courier_user`)
- Create/view dispatches
- Cannot cancel or confirm delivery
- Based on POS User rights

**Courier Manager** (`group_courier_manager`)
- All Courier User rights
- Mark as delivered
- Confirm customer receipt
- Cancel dispatches
- Manage courier companies

## Technical Details

### Models
- `courier.dispatch` - Main dispatch record
- `courier.dispatch.line` - Dispatch items
- `courier.company` - Courier company master data
- `pos.order` - Extended with dispatch functionality
- `stock.move` - Extended with dispatch reference

### Wizards
- `register.courier.dispatch.wizard` - Create dispatch
- `confirm.delivery.wizard` - Confirm customer receipt

### Sequences
- Format: `COURIER/YYYY/XXXX`
- Example: `COURIER/2025/0001`

### Stock Locations
- `Courier Transit` - Transit location for items with courier

## Reporting

### Available Reports
1. **Dispatch Summary**
   - Filter by date, status, courier
   - Group by payment responsibility

2. **Pending Deliveries**
   - All in_transit dispatches
   - Overdue tracking

3. **Courier Fee Analysis**
   - Pivot analysis
   - Total COGS impact
   - By customer/product

## Best Practices

1. **Always add tracking numbers** when available
2. **Upload courier documents** (waybills, receipts)
3. **Take photos on delivery** for proof
4. **Record customer complaints** immediately
5. **Configure COGS account** before first use
6. **Use courier companies** for frequent couriers
7. **Cancel properly** (reverses stock & accounting)

## Troubleshooting

### Issue: Cannot find "Dispatch via Courier" button
**Solution:** Ensure:
- POS order is in 'paid', 'done', or 'invoiced' state
- User has "Courier User" access rights

### Issue: Error creating journal entry
**Solution:** 
- Configure COGS account in Settings
- Ensure payment journal is selected
- Check account type is expense_direct_cost

### Issue: Stock moves not created
**Solution:**
- Check Courier Transit location exists
- Verify POS config has source location
- Check product is stockable

## Support & Documentation

- Module Version: 18.0.1.0.0
- Odoo Version: 18.0 Enterprise
- Author: Crown Paints Kenya - ATIQ
- License: LGPL-3

## Changelog

### Version 1.0.0 (2025-11-29)
- Initial release
- Full courier dispatch workflow
- Stock and accounting integration
- Multi-state tracking
- Customer confirmation
- Comprehensive reporting

## Future Enhancements (Roadmap)

- [ ] SMS/Email notifications to customers
- [ ] Courier API integration (DHL, FedEx)
- [ ] Barcode scanning for dispatch
- [ ] Customer portal access
- [ ] Courier performance analytics
- [ ] Automated delivery status updates

---

**Made with ❤️ for Crown Paints Kenya**
