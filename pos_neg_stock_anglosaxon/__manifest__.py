# -*- coding: utf-8 -*-
# Module: POS Negative Stock Anglo-Saxon Finance Fix
# Allows POS overselling by force-validating outgoing pickings, records
# negative stock.valuation.layers at AVCO, and reconciles them on receipt
# using FIFO with Anglo-Saxon price difference journal entries.
# Costing: AVCO | Valuation: Automated | Accounting: Anglo-Saxon
{
    'name': 'POS Negative Stock Anglo-Saxon Finance Fix',
    'version': '18.0.1.3.2',
    'category': 'Inventory/Point of Sale',
    'summary': 'AVCO price difference reconciliation for POS oversell in Anglo-Saxon accounting',
    'author': 'Custom',
    'website': '',
    'depends': [
        'point_of_sale',
        'stock_account',
        'account',
        'purchase',       # defines property_account_creditor_price_difference on product.category
        'purchase_stock', # links PO receipts to stock moves (price_unit on stock.move)
        'mrp',            # Manufacturing settings page for the tinted oversell policy
    ],
    'data': [
        'security/ir.model.access.csv',
        # Report actions must load before views that reference them in menuitems
        'report/neg_stock_reconciliation_report.xml',
        'report/neg_stock_reconciliation_template.xml',
        # Views (may reference actions defined above)
        'views/product_category_view.xml',
        'views/stock_valuation_layer_view.xml',
        'views/neg_stock_reconciliation_view.xml',
        'views/res_config_settings_view.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_neg_stock_anglosaxon/static/src/app/temporary_lot_guard/constants.js',
            'pos_neg_stock_anglosaxon/static/src/app/temporary_lot_guard/logger.js',
            'pos_neg_stock_anglosaxon/static/src/app/temporary_lot_guard/policy.js',
            'pos_neg_stock_anglosaxon/static/src/app/temporary_lot_guard/dialogs.js',
            'pos_neg_stock_anglosaxon/static/src/app/temporary_lot_guard/pos_store_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
