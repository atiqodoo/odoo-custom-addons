# -*- coding: utf-8 -*-
{
    'name': "POS: Block Price Below Cost",
    'version': '18.0.2.0.0',
    'category': 'Point of Sale',
    'summary': 'Blocks POS sales below cost with real-time warnings and manager PIN override',
    'description': """
        Prevents selling at a loss in Point of Sale.
        Features:
        - standard_price (cost) loaded into POS session for all products
        - Visual ⚠ badge on any order line priced below cost (live, updates instantly)
        - Real-time warning toast when cashier sets price or discount below cost
        - Hard block at payment validation with manager PIN override dialog
        - Refund / return lines (qty < 0) are always exempt from all checks
        - Server-side PIN validation: only POS Manager group employees can override
    """,
    'depends': ['point_of_sale', 'web', 'hr', 'pos_cod'],
    'data': [],
    'assets': {
        'point_of_sale._assets_pos': [
            # CSS first so styles are available when components render
            'pos_block_price_cost/static/src/css/pos_restriction.css',
            # XML templates before the JS that references them
            'pos_block_price_cost/static/src/xml/manager_pin_dialog.xml',
            'pos_block_price_cost/static/src/xml/orderline_warning.xml',
            'pos_block_price_cost/static/src/xml/cod_check_dialog.xml',
            # JS patches
            'pos_block_price_cost/static/src/js/manager_pin_dialog.js',
            'pos_block_price_cost/static/src/js/orderline_patch.js',
            'pos_block_price_cost/static/src/js/pos_restriction.js',
            'pos_block_price_cost/static/src/js/global_discount_check.js',
            'pos_block_price_cost/static/src/js/cod_check.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}