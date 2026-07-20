# -*- coding: utf-8 -*-
{
    'name': 'Vendor Combined LPO Bill Wizard',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Create one vendor bill from multiple LPOs with vendor price validation',
    'description': """
Vendor Combined LPO Bill Wizard
===============================
Creates one controlled vendor bill from multiple eligible LPOs for the same
vendor, company, currency, and invoice calculation profile.
    """,
    'depends': [
        'purchase_stock',
        'account',
        'purchase_net_price_compute',
        'vendor_price_check',
        'vendor_purchase_promotions',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/combined_lpo_bill_wizard_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
