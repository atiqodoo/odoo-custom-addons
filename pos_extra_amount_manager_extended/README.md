# POS Extra Amount & Base Profit Manager

Complete two-tier commission distribution system for Odoo 18 Point of Sale with automatic accounting entries.

## Overview

This module provides a sophisticated two-tier commission system for POS orders:

**TIER 1: Extra Amount Distribution**
- Track extra amounts charged above pricelist
- Distribute premium pricing commissions
- Full accounting with 3 journal entries

**TIER 2: Base Profit Distribution**
- Share profit on pricelist itself (excl VAT)
- Only accessible after TIER 1 fully distributed
- Simple accounting with 1 journal entry

## Features

### TIER 1: Extra Amount
- ✅ **Precise Calculation**: `(Paid Price - Pricelist Price) × Quantity`
- ✅ **Quantity Toggle**: Calculate for full quantity or single unit
- ✅ **Flexible Distribution**: By percentage or fixed amount
- ✅ **Complete Accounting**: 3 journal entries (Revenue + COGS + Commission)
- ✅ **Prevent Over-distribution**: Validates against remaining amount

### TIER 2: Base Profit
- ✅ **VAT-Exclusive Profit**: `(Pricelist excl VAT - Purchase Price) × Quantity`
- ✅ **Locked Access**: Must complete TIER 1 first
- ✅ **Same Quantity Toggle**: Consistent behavior across tiers
- ✅ **Simple Accounting**: 1 journal entry (Commission only)
- ✅ **Separate COGS Account**: Better P&L reporting

### Common Features
- ✅ Multiple distributions per tier per order
- ✅ State management with workflow
- ✅ Complete audit trail with chatter
- ✅ Smart buttons for easy access
- ✅ Validation and error handling

## Installation

1. Copy the `pos_extra_amount_manager_extended` folder to your Odoo addons directory
2. Update the apps list: `Settings → Apps → Update Apps List`
3. Search for "POS Extra Amount & Base Profit Manager"
4. Click Install

## Configuration

### Configure Default COGS Accounts

Go to: `Settings → Point of Sale → Commission Distribution`

Set two accounts:

1. **TIER 1: Extra Commission COGS Account**
   - For extra amount commission distributions
   - Can be same or different from TIER 2

2. **TIER 2: Base Profit Commission COGS Account**
   - For base profit commission distributions
   - Recommended: Use separate account for better P&L analysis

**Example Chart of Accounts:**
```
5100 - COGS - Extra Commissions (TIER 1)
5200 - COGS - Base Profit Commissions (TIER 2)
```

## Usage

### Complete Two-Tier Workflow

#### TIER 1: Extra Amount Distribution

**Step 1: Calculate Extra Amount**
1. Open a POS Order
2. Click **"Calculate Extra"** button in header
3. Review extra amounts in **"Extra Amounts"** tab
4. Toggle `Calculate with Quantity` per line if needed

**Step 2: Distribute Extra Amount**
1. Click **"Distribute Extra"** button
2. Choose input method:
   - **Percentage**: Enter % of remaining extra
   - **Fixed Amount**: Enter specific amount
3. Select:
   - Payment Journal (Cash, M-Pesa, Bank)
   - Recipient (Partner)
   - Extra Commission COGS Account
4. Click **"Create Distribution"**

**Step 3: Complete TIER 1**
- Repeat Step 2 until `Remaining Extra Amount = 0`
- Status: `Extra State = Distributed`

#### TIER 2: Base Profit Distribution

**Step 4: Calculate Base Profit (Unlocked!)**
1. After TIER 1 complete, **"Calculate Base Profit"** button appears
2. Click button
3. Review base profit in **"Base Profit"** tab
4. See: Pricelist excl VAT, Purchase Price, Profit per line

**Step 5: Share Base Profit**
1. Click **"Share Base Profit"** button
2. Choose input method:
   - **Percentage**: Enter % of remaining profit
   - **Fixed Amount**: Enter specific amount
3. Select:
   - Payment Journal (Cash, M-Pesa, Bank)
   - Recipient (Partner)
   - Base Profit Commission COGS Account
4. Click **"Create Distribution"**

**Step 6: Multiple Distributions (Optional)**
- Can share profit with multiple recipients
- Repeat Step 5 as needed
- Cannot exceed total base profit

## Calculation Examples

### Example Order
```
Product: Paint 5L
Quantity: 10 units
Pricelist (incl 16% VAT): 1,740/unit
Pricelist (excl VAT): 1,500/unit
Purchase Cost: 1,000/unit
Customer Paid: 2,000/unit
```

### TIER 1: Extra Amount
```
Extra per unit = 2,000 - 1,740 = 260

With calculate_with_quantity = ON:
Total extra = 260 × 10 = 2,600

With calculate_with_quantity = OFF:
Total extra = 260 × 1 = 260
```

### TIER 2: Base Profit
```
Base profit per unit = 1,500 - 1,000 = 500

With calculate_with_quantity = ON:
Total base profit = 500 × 10 = 5,000

With calculate_with_quantity = OFF:
Total base profit = 500 × 1 = 500
```

### Distribution Example
```
TIER 1 Distribution:
- 100% to Sales Rep = 2,600
Status: Extra fully distributed ✓

TIER 2 Distribution:
- 30% to Sales Rep = 1,500
- 20% to Manager = 1,000
- Remaining: 2,500
Status: Base profit partially shared
```

## Accounting

### TIER 1: Extra Amount (3 Entries Per Distribution)

**Entry 1: Extra Revenue**
```
Dr: Cash/M-Pesa              [Amount]
    Cr: Extra Revenue             [Amount]
```

**Entry 2: Product COGS**
```
Dr: COGS - Product           [Proportional COGS]
    Cr: Stock Valuation           [Proportional COGS]
```

**Entry 3: Commission**
```
Dr: COGS - Extra Commission  [Amount]
    Cr: Cash/M-Pesa               [Amount]
```

### TIER 2: Base Profit (1 Entry Per Distribution)

**Entry: Commission Only**
```
Dr: COGS - Base Commission   [Amount]
    Cr: Cash/M-Pesa               [Amount]
```

**Why only 1 entry?**
- Base sale revenue already recorded in normal POS entry
- Base product COGS already recorded in normal POS entry
- Only commission payout needs accounting
- Cleaner, no duplicate entries

## UI Features

### Two Separate Tabs

**Tab 1: "Extra Amounts"**
- Summary: Total, Distributed, Remaining
- Line details with quantity toggle
- Extra amount breakdown per line

**Tab 2: "Base Profit"** (NEW!)
- 🔒 Locked until TIER 1 complete
- Summary: Total, Shared, Remaining
- Line details with profit breakdown
- VAT-exclusive calculations shown

### Smart Buttons

**Extra Distributions** - Shows count of TIER 1 distributions

**Base Profit** - Shows count of TIER 2 distributions

### Status Bars

**Extra State**: draft → calculated → distributed

**Profit State**: draft → calculated → shared (visible after TIER 1)

## Button Visibility Logic

```
Calculate Extra:
  Visible when: extra_state = 'draft'

Distribute Extra:
  Visible when: extra_state = 'calculated'

Calculate Base Profit: (NEW!)
  Visible when: extra_state = 'distributed' 
                AND remaining_extra_amount = 0

Share Base Profit: (NEW!)
  Visible when: profit_state = 'calculated'

Reset:
  Visible when: extra_state != 'draft'
  Only POS Managers
```

## Security

### Access Rights

**POS User:**
- Create and view distributions (both tiers)
- Cannot delete posted distributions

**POS Manager:**
- Full access including deletion
- Can reset states
- Override default accounts

### Restrictions

- Cannot delete posted distributions
- Cannot distribute more than total (either tier)
- Cannot reset state when distributions exist
- Cannot access TIER 2 until TIER 1 complete

## Technical Details

### Dependencies
- `point_of_sale`
- `account`
- `stock_account`

### New Models
- `pos.base.profit.distribution` (TIER 2 model)
- `pos.base.profit.distribution.wizard` (TIER 2 wizard)

### Extended Models
- `pos.order` - Added base profit fields and workflow
- `pos.order.line` - Added base profit calculation
- `res.config.settings` - Added base profit COGS account

### Fields Added to POS Order Line

**TIER 1 (Existing):**
- `calculate_with_quantity` - Toggle for both tiers
- `pricelist_price_incl` - Pricelist with VAT
- `paid_price_per_unit` - Actual price paid
- `extra_amount_per_unit` - Extra per unit
- `total_extra_amount` - Total extra
- `product_cost` - AVCO cost

**TIER 2 (NEW):**
- `pricelist_price_excl_vat` - Pricelist without VAT
- `base_profit_per_unit` - Profit per unit
- `total_base_profit` - Total profit

### Fields Added to POS Order

**TIER 1 (Existing):**
- `extra_state` - Workflow state
- `total_extra_amount` - Total extra
- `total_distributed_amount` - Distributed
- `remaining_extra_amount` - Remaining
- `extra_distribution_ids` - Distributions

**TIER 2 (NEW):**
- `profit_state` - Workflow state
- `total_base_profit` - Total profit
- `total_shared_base_profit` - Shared
- `remaining_base_profit` - Remaining
- `base_profit_distribution_ids` - Distributions
- `base_profit_distribution_count` - Count

## Workflow States

### TIER 1: Extra Amount

**Draft**
- Initial state
- No calculations
- Action: Click "Calculate Extra"

**Calculated**
- Extra amounts computed
- Ready for distribution
- Action: Click "Distribute Extra"

**Distributed**
- All extra distributed (remaining = 0)
- TIER 2 unlocked!
- Action: Click "Calculate Base Profit"

### TIER 2: Base Profit

**Draft**
- Locked until TIER 1 complete
- No calculations
- Waiting for TIER 1

**Calculated**
- Base profit computed
- Ready for sharing
- Action: Click "Share Base Profit"

**Shared**
- At least one distribution posted
- Can create more if profit remains

## Frequently Asked Questions

### Q: Why two tiers?
**A**: Incentivize both premium pricing (extra) and standard margin (base profit) separately with different commission rates.

### Q: Can I skip TIER 1?
**A**: No. TIER 2 only unlocks after TIER 1 fully distributed. This prevents confusion and ensures controlled workflow.

### Q: Do I need to distribute 100% of base profit?
**A**: No. Unlike TIER 1 (must complete 100%), you can partially distribute base profit.

### Q: Why is base profit VAT-exclusive?
**A**: VAT is government's money, not profit. Excluding VAT gives accurate accounting profit.

### Q: Can I use the same COGS account for both tiers?
**A**: Yes, but separate accounts provide better P&L analysis. You can see extra commissions vs base profit commissions.

### Q: What if I change the quantity toggle?
**A**: It applies to BOTH tiers consistently. Toggle ON = full quantity, OFF = single unit only.

### Q: Can I create multiple distributions per tier?
**A**: Yes! You can split extra amount and base profit among multiple recipients.

### Q: What happens to distributions if I delete the POS order?
**A**: All distributions (both tiers) are deleted automatically (cascade delete).

## Troubleshooting

### "Calculate Base Profit button not visible"
- Check: Extra state must be 'distributed'
- Check: Remaining extra amount must be 0
- Solution: Complete all TIER 1 distributions first

### "Distribution exceeds available"
- You're trying to distribute more than remaining
- Check remaining amount in wizard
- Reduce percentage or fixed amount

### "No default account in journal"
- Configure default account for payment journal
- Go to: Accounting → Configuration → Journals
- Edit journal → Set default account

### "Cannot reset state"
- Distributions exist (either tier)
- Must delete distributions first
- Only POS Managers can delete posted distributions

## Support

For issues or questions:
- Email: support@yourcompany.com
- Website: https://www.yourcompany.com

## License

LGPL-3

## Author

Your Company

## Version

18.0.2.0.0 - Complete Two-Tier System for Odoo 18 Enterprise & Community
