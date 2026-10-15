{
    'name': 'Vendor Purchase Promotions',
    'version': '18.0.1.3.0',
    'category': 'Purchase',
    'summary': 'Modular vendor promotions, FOC tracking, Gamma pricing, and payment holds',
    'description': """
Vendor Purchase Promotions
==========================
* Data-driven buy-X-get-Y vendor promotion rules.
* Separate charged and FOC purchase lines for correct partial receipts.
* Modular Gamma discount and tint-charge calculator.
* Vendor-bill audit fields and promised-price integration.
* Payment hold and approval workflow for outstanding FOC commitments.
    """,
    'depends': [
        'purchase_stock',
        'stock_account',
        'purchase_net_price_compute',
        'vendor_price_check',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/promotion_profiles.xml',
        'data/vendor_promotion_sequence.xml',
        'views/vendor_promotion_views.xml',
        'views/res_config_settings_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking_views.xml',
        'views/promotion_override_log_views.xml',
        'views/promotion_substitution_override_log_views.xml',
        'views/vendor_price_wizard_views.xml',
        'views/account_move_views.xml',
        'reports/purchase_order_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'vendor_purchase_promotions/static/src/js/promotion_warning_action.js',
            'vendor_purchase_promotions/static/src/js/substitution_mismatch_warning_action.js',
            'vendor_purchase_promotions/static/src/scss/promotion_warning.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
