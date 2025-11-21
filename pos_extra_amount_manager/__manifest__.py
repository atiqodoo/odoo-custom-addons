# -*- coding: utf-8 -*-
{
    'name': 'POS Extra Amount Manager',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Manage and distribute extra amounts charged in POS orders with COGS tracking',
    'description': """
POS Extra Amount Manager
========================
This module helps track and distribute extra amounts charged above pricelist prices in POS orders.

Key Features:
-------------
* Calculate extra amount per POS order line (paid vs pricelist price)
* Toggle to calculate with full quantity or single unit
* Distribution wizard with percentage or fixed amount options
* Automatic journal entries for revenue and COGS (Anglo-Saxon accounting)
* Multiple distributions allowed with remaining amount tracking
* Prevent duplicate executions with state management
* AVCO cost tracking for accurate profit calculation

Accounting:
-----------
* Entry 1: Extra Revenue (Debit Cash/M-Pesa, Credit Extra Revenue)
* Entry 2: Product COGS (Debit COGS - Product, Credit Stock Valuation)
* Entry 3: Commission COGS (Debit COGS - Commission, Credit Cash/M-Pesa)
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'account',
        'stock_account',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_order_views.xml',
        'views/pos_config_views.xml',
        'views/pos_extra_distribution_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/pos_extra_distribution_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
