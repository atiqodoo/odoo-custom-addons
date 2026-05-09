# -*- coding: utf-8 -*-
# POS Cash on Delivery (COD)
#
# Workflow:
#   1. Cashier clicks COD on product screen → wizard collects customer/delivery details
#   2. Backend: stock moves validated immediately, DR COD AR / CR Sales entry posted
#   3. Order stays pending across sessions until delivery collects cash
#   4. COD Orders screen in POS lists pending orders; cashier clicks Receive Payment
#   5. Backend: DR Cash / CR COD AR entry posted, AR reconciled, order marked paid
#
# Accounting safety:
#   COD uses a dedicated AR account (asset_receivable, reconcile=True) configured in
#   POS settings. This account is excluded from pos_credit_limit's total_due via a
#   subtraction override in get_credit_info(), keeping COD and credit-sale pools separate.
#   COD journal entries use move_type='entry' (not out_invoice) so they never appear in
#   the overdue invoice query used by Gate 1.5 of pos_credit_limit.
{
    'name': 'POS Cash on Delivery',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'COD: stock deducted at dispatch, payment collected at delivery',
    'author': 'Custom Development',
    'depends': [
        'point_of_sale',
        'pos_credit_limit',
        'account',
        'stock',
        'hr',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_config_views.xml',
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            # Layer 0 — Logger utility (no dependencies)
            'pos_cod/static/src/app/utils/cod_logger.js',
            # Layer 1 — Store patch (RPC methods on PosStore)
            'pos_cod/static/src/app/patches/pos_store_patch.js',
            # Layer 2 — UI components (depend on logger + store)
            'pos_cod/static/src/app/components/cod_wizard/CodWizard.xml',
            'pos_cod/static/src/app/components/cod_wizard/CodWizard.js',
            'pos_cod/static/src/app/components/cod_banner/CodBanner.xml',
            'pos_cod/static/src/app/components/cod_banner/CodBanner.js',
            # Layer 3 — Dialogs and Screens
            'pos_cod/static/src/app/components/cod_line_details_dialog/CodLineDetailsDialog.xml',
            'pos_cod/static/src/app/components/cod_line_details_dialog/CodLineDetailsDialog.js',
            'pos_cod/static/src/app/components/cod_return_dialog/CodReturnDialog.xml',
            'pos_cod/static/src/app/components/cod_return_dialog/CodReturnDialog.js',
            'pos_cod/static/src/app/screens/cod_orders_screen/cod_orders_screen.scss',
            'pos_cod/static/src/app/screens/cod_orders_screen/CodOrdersScreen.xml',
            'pos_cod/static/src/app/screens/cod_orders_screen/CodOrdersScreen.js',
            # Layer 4 — Product screen patch (COD button)
            'pos_cod/static/src/app/components/cod_button/CodButton.xml',
            'pos_cod/static/src/app/components/cod_button/CodButton.js',
            # Layer 5 — Payment screen patch (COD payment guard)
            'pos_cod/static/src/app/patches/payment_screen_patch.js',
            # Layer 6 — Navbar patch (mounts CodBanner into the POS header)
            'pos_cod/static/src/app/patches/navbar_patch.xml',
            'pos_cod/static/src/app/patches/navbar_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
