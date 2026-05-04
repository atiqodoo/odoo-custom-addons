# -*- coding: utf-8 -*-
{
    'name': 'POS Extra Amount & Base Profit Manager',
    'version': '18.0.3.0.0',
    'category': 'Point of Sale',
    'summary': 'Two-tier commission system with VAT split: Extra amounts + Base profit distribution',
    'description': """
POS Extra Amount & Base Profit Manager
=======================================
Complete two-tier commission distribution system for POS orders with proper VAT accounting.

TIER 1: Extra Amount Distribution (with VAT Split)
---------------------------------------------------
* Track extra amounts charged above pricelist
* Distribute premium pricing commissions
* Journal entry splits VAT automatically:
  - Dr COGS Commission (excl VAT)
  - Dr Output VAT (VAT portion)
  - Cr Cash/Bank (total incl VAT)

TIER 2: Base Profit Distribution
---------------------------------
* Share profit on pricelist itself (excl VAT)
* Accessible after Tier 1 distributed OR when no extra exists
* 1 simple journal entry per distribution

Key Features:
-------------
* Automatic VAT split on extra commissions (Option 3: Most Accounting-Correct)
* Calculate extra: (Paid - Pricelist) × Quantity
* Calculate base profit: (Pricelist excl VAT - Purchase) × Quantity
* Quantity toggle applies to both tiers
* Prevent over-distribution on each tier
* Separate COGS accounts for reporting
* Proper VAT tracking for tax compliance
* Complete audit trail with state management

Accounting:
-----------
Tier 1 creates 3 entries: Extra Revenue + Product COGS + Commission
Tier 2 creates 1 entry: Commission only (sale/COGS already recorded)

Workflow:
---------
1. Calculate Extra Amount
2. Distribute Extra (must complete 100%)
3. Calculate Base Profit (unlocked when extra done)
4. Share Base Profit

Both POS and accounting staff benefit from clear separation.
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'account',
        'stock_account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_order_views.xml',
        'views/pos_extra_distribution_views.xml',
        'views/pos_base_profit_distribution_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/pos_extra_distribution_wizard_views.xml',
        'wizard/pos_base_profit_distribution_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
}
