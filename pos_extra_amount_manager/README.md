# POS Extra Amount Manager

## Overview
This Odoo 18 module helps track and distribute extra amounts charged above pricelist prices in Point of Sale orders, with full COGS (Cost of Goods Sold) tracking using Anglo-Saxon accounting principles.

## Features

### 1. Extra Amount Calculation
- **Automatic Detection**: Identifies when products are sold at prices higher than pricelist prices
- **Precise Calculation**: Uses `(price_subtotal_incl / qty) - pricelist_price` for accurate per-unit pricing
- **VAT Inclusive**: Works with VAT-inclusive pricelist prices (no additional tax calculation)
- **Quantity Toggle**: Per-line boolean to calculate extra for full quantity or single unit only

### 2. Distribution Management
- **Flexible Input**: Distribute by percentage OR fixed amount
- **Multiple Distributions**: Allow multiple distributions from same order, tracking remaining amount
- **Partner Tracking**: Assign each distribution to a specific partner (salesperson, etc.)
- **State Management**: Prevents duplicate executions with draft → calculated → distributed workflow

### 3. Automatic Accounting (Anglo-Saxon)
Creates 3 journal entries per distribution:

**Entry 1: Extra Revenue**
```
Debit:  Cash/M-Pesa Account     | Distribution Amount
Credit: Extra Revenue Account   | Distribution Amount
```

**Entry 2: Product COGS**
```
Debit:  COGS - Product Account      | Proportional COGS
Credit: Stock Valuation Account     | Proportional COGS
```

**Entry 3: Commission Payout**
```
Debit:  COGS - Commission Account   | Distribution Amount
Credit: Cash/M-Pesa Account         | Distribution Amount
```

### 4. AVCO Cost Tracking
- Uses `product.standard_price` for accurate product costing
- Calculates proportional COGS: `(distribution_amount / total_extra) × total_cogs`
- Respects quantity toggle for cost calculation

## Installation

1. Copy the module to your Odoo addons directory
2. Update app list: Settings → Apps → Update Apps List
3. Search for "POS Extra Amount Manager"
4. Click Install

## Configuration

### 1. Set Default Accounts
Navigate to: **Point of Sale → Configuration → Settings → Extra Amount Management**

Configure default accounts:
- **Extra Revenue Account**: Income account for extra revenue (can override per distribution)
- **COGS - Product Account**: Expense account for product cost
- **COGS - Commission Account**: Expense account for commissions/distributions
- **Stock Valuation Account**: Asset account for inventory valuation

### 2. Ensure Products Use AVCO
- Go to product category
- Set **Costing Method**: Average Cost (AVCO)
- Set **Inventory Valuation**: Automated

## Usage

### Step 1: Calculate Extra Amount
1. Open a POS Order (backend): **Point of Sale → Orders → Orders**
2. Click **"Calculate Extra Amount"** button
3. System calculates:
   - Extra amount per line (paid - pricelist price)
   - Total extra amount
   - Total product COGS
4. Order state changes to **"Calculated"**

### Step 2: Toggle Quantity Calculation (Optional)
1. In order lines, toggle **"Calculate with Quantity"** field:
   - ✅ **ON** (default): Total extra = extra_per_unit × quantity
   - ❌ **OFF**: Total extra = extra_per_unit × 1 (only 1 unit counted)

### Step 3: Distribute Amount
1. Click **"Distribute Amount"** button
2. Wizard opens with:
   - **Total Extra Amount** (readonly)
   - **Remaining Amount** (readonly)
   - **Total COGS** (readonly)

3. **Input Method**: Choose one:
   - **Percentage**: Enter % of remaining amount (e.g., 20%)
   - **Fixed Amount**: Enter exact amount (e.g., KES 500)

4. **Select Payment Journal**: Cash, M-Pesa, Bank, etc.

5. **Select Recipient**: Partner who receives this distribution

6. **Review/Edit Accounts**: Default accounts loaded, can be changed

7. Click **"Create Distribution"**

### Step 4: Review Results
- 3 journal entries created automatically
- Distribution record saved with all details
- Order state changes to **"Distributed"**
- Remaining amount updated for future distributions

## Example Scenario

**POS Order #001**:
- Product A: Pricelist KES 1,160 (VAT incl), Paid KES 1,252.80, Qty: 5, Toggle: ON
  - Extra: KES 92.80 per unit × 5 = KES 464
  - COGS: KES 600 × 5 = KES 3,000

- Product B: Pricelist KES 580, Paid KES 580, Qty: 3
  - Extra: KES 0 (no extra)

**Total Extra**: KES 464  
**Total COGS**: KES 3,000

**User Distributes 50% (KES 232)**:

**Entries Created**:
1. Revenue: Debit Cash KES 232, Credit Revenue KES 232
2. Product COGS: Debit COGS KES 1,500, Credit Stock KES 1,500
3. Commission: Debit COGS-Commission KES 232, Credit Cash KES 232

**Remaining**: KES 232 (can distribute again later)

## Fields Reference

### POS Order Line
- `pricelist_price_incl`: Pricelist price (VAT inclusive)
- `paid_price_per_unit`: Actual paid price = price_subtotal_incl / qty
- `extra_amount_per_unit`: Difference between paid and pricelist
- `calculate_with_quantity`: Boolean toggle
- `total_extra_amount`: Extra amount for this line
- `product_cost`: AVCO cost for this line

### POS Order
- `extra_state`: draft / calculated / distributed
- `total_extra_amount`: Sum of all line extras
- `total_extra_cogs`: Sum of all product costs
- `total_distributed_amount`: Sum of distributions
- `remaining_extra_amount`: Available for distribution

### Distribution
- `distribution_amount`: Amount distributed
- `distribution_cogs`: Proportional product cost
- `percent`: Percentage used (if applicable)
- `payment_journal_id`: Payment method
- `partner_id`: Recipient
- `revenue_move_id`: Revenue journal entry
- `cogs_product_move_id`: Product COGS entry
- `cogs_commission_move_id`: Commission entry
- `state`: draft / posted / cancelled

## Technical Details

### Dependencies
- `point_of_sale`: Core POS module
- `account`: Accounting
- `stock_account`: Stock valuation integration

### Models
- `pos.order`: Extended with extra amount management
- `pos.order.line`: Extended with calculation fields
- `pos.extra.distribution`: New model for distribution records
- `pos.extra.distribution.wizard`: Transient model for wizard
- `res.config.settings`: Extended with default accounts

### Security
- POS Users: Can create and view distributions
- POS Managers: Full access including deletion

## Best Practices

1. **Always Calculate First**: Click "Calculate Extra Amount" before distributing
2. **Review Line Toggles**: Check quantity toggles match your business logic
3. **Configure Defaults**: Set default accounts in settings for faster workflow
4. **Multiple Distributions**: Use for partial distributions over time
5. **Journal Review**: Review generated entries before posting (if needed)

## Troubleshooting

### "Please calculate extra amounts first"
→ Click "Calculate Extra Amount" button before distributing

### "Distribution amount exceeds available amount"
→ Check remaining amount, already distributed amount may exceed total

### "No default account configured"
→ Configure default accounts in POS Settings

### Extra amount showing as zero
→ Verify pricelist prices are set correctly and VAT inclusive

## Support & Customization

For customization or support:
- Email: support@yourcompany.com
- Website: https://www.yourcompany.com

## License
LGPL-3

## Version
18.0.1.0.0

## Author
Your Company
