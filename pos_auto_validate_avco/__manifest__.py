# -*- coding: utf-8 -*-
{
    'name': 'POS Auto-Validate AVCO',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Point of Sale',
    'summary': (
        'Replaces 3 automation rules with AVCO-safe, Anglo-Saxon-correct '
        'auto-dispatch for POS: purchase receipt, customer return, and MO triggers'
    ),
    'depends': [
        'stock',
        'mrp',
        'point_of_sale',
        'pos_neg_stock_anglosaxon',  # must load before us so our _action_done is outermost
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
