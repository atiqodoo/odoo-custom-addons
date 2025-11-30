# POS Deferred / Pending Collection (Backend Only)

## Overview

This module allows customers to pay the full bill in POS, take some items immediately, and leave the rest in the shop for later collection - all managed 100% from the backend with zero changes to the POS interface.

Perfect for paint retail & tinting stores where customers may need multiple trips to collect large orders.

## Key Features

- ✅ **100% Backend Operation** - Zero POS interface changes
- ✅ **Track Paid-But-Not-Collected Items** - Know exactly what's waiting for pickup
- ✅ **Reserve Inventory** - Items moved to dedicated holding location
- ✅ **Full Audit Trail** - Link back to original POS receipt and customer
- ✅ **Easy Search & Collection** - Find pending items by customer, phone, barcode
- ✅ **Printable Labels** - Physical labels with barcodes for items in storage
- ✅ **Reporting & Aging** - Track pending collections by age (0-7d, 8-30d, 30+d)

## Workflow

### Step 1: Normal POS Sale
- Cashier rings up items
- Customer pays full amount
- Receipt printed
- Order closed (no extra action needed)

### Step 2: Register Deferred Collection (30-60 seconds)
- Backend user opens the POS order
- Clicks "Register Deferred Collection"
- Adjusts "Taken Today" quantities
- System creates Pending Collection record
- Stock moved to holding location
- Label printed automatically

### Step 3: Physical Storage
- Staff attaches printed label to items
- Places on designated "Pending Collection" shelf

### Step 4: Customer Returns
- Staff searches Pending Collections (by phone/receipt/barcode)
- Opens record
- Clicks "Customer Collected"
- Selects quantities being picked up
- Stock released back to main location

## Configuration

### Initial Setup

1. **Install Module**
   ```
   Apps → Search "POS Deferred" → Install
   ```

2. **Verify Stock Location**
   - Location created automatically: "Customer Holding Area"
   - Path: Inventory → Configuration → Locations
   - Verify it's marked as Internal type

3. **Assign User Rights**
   - Settings → Users & Companies → Users
   - Add users to "Pending Collection User" group
   - Managers get "Pending Collection Manager" group

### Menu Access

- **Paint Retail → Pending Collections** (main menu)
- **Point of Sale → Pending Collections** (alternative access)
- **Point of Sale → Orders → POS Orders** (smart button shows count)

## Usage Examples

### Example 1: Customer Orders 20L Paint, Takes 5L Today

1. POS rings up: 4x 5L cans
2. Customer pays full amount (e.g., KES 10,000)
3. Customer takes 1 can today
4. Backend: Open order → "Register Deferred Collection"
5. Adjust: Taken Today = 1, Left in Store = 3
6. Confirm → Label prints → Staff stores 3 cans
7. Customer returns next week → Search by phone → Mark collected

### Example 2: Tinted Paint - Multiple Colors

1. POS order: 3 different tinted colors
2. Customer takes Color A only
3. Backend: Register deferred collection for Colors B & C
4. Each line includes tint color code
5. Easy identification when customer returns

## Reports

### Pending Collection Label
- A5-sized printable label
- Includes barcode for quick scanning
- Customer details, POS receipt reference
- List of pending items with color codes
- Location information

### Search & Filters
- Search by: Customer name, phone, mobile, POS receipt, barcode
- Filter by: Status (Draft/Partial/Done/Cancelled)
- Age ranges: 0-7 days, 8-30 days, 30+ days
- Group by: Customer, Status, Date Left

## Technical Details

### Models Created

- `paint.pending.collection` - Main tracking model
- `paint.pending.collection.line` - Individual item lines
- `register.deferred.collection.wizard` - Initial registration wizard
- `collect.pending.items.wizard` - Collection processing wizard

### Extended Models

- `pos.order` - Added smart button and action
- `pos.order.line` - Added taken_qty field

### Stock Integration

- Automatic stock moves to/from holding location
- Full traceability with move references
- Support for lot/serial tracking
- Integration with existing warehouse operations

### Security Groups

- **Pending Collection User** - Create and manage pending collections
- **Pending Collection Manager** - Full access including cancellation

## Best Practices

1. **Daily Routine**
   - Review pending collections at end of day
   - Follow up on items older than 7 days
   - Contact customers with items over 30 days old

2. **Physical Organization**
   - Use printed labels on all items
   - Organize by date or customer
   - Maintain separate shelf/area

3. **Customer Communication**
   - Give customer a copy of the label
   - Note collection deadline if policy exists
   - Remind customer to bring receipt or label

4. **Inventory Management**
   - Regular spot checks of holding location
   - Reconcile physical items vs system
   - Handle expired/abandoned items per policy

## Troubleshooting

### Items Not Moving to Holding Location

**Check:**
- Holding location exists and is active
- User has inventory rights
- Source location configured in POS settings

### Cannot Find Pending Collection

**Search Tips:**
- Try phone number without country code
- Search POS receipt number
- Scan barcode on printed label
- Check if accidentally marked as collected

### Label Not Printing

**Verify:**
- Report installed correctly
- Print settings configured
- PDF generation working
- Browser allows pop-ups

## Support & Customization

For support or custom modifications:
- Email: support@crownkenya.co.ke
- Developer: ATIQ - Crown Kenya PLC
- Website: https://www.mzaramopaintsandwallpaper.com

## Version History

### Version 1.0.0 (2025-11-28)
- Initial release
- Backend-only workflow
- Stock location integration
- Printable labels
- Aging reports
- Full search capabilities

## License

LGPL-3

## Credits

Developed by ATIQ for Crown Kenya PLC
Mzaramo Paints & Wallpaper Division
