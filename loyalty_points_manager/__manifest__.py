# -*- coding: utf-8 -*-
{
    'name': 'Loyalty Points Manager',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Manual management of customer loyalty points with accounting integration',
    'description': """
        Loyalty Points Manager
        ======================
        This module allows manual management of customer loyalty points:
        * Add or reduce loyalty points manually
        * Wizard interface with customer search
        * Real-time balance calculation
        * Full accounting integration
        * Audit trail for all point adjustments
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'loyalty',
        'account',
        'point_of_sale',
        'pos_loyalty',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/loyalty_points_adjustment_views.xml',
        'wizard/loyalty_points_wizard_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            # 1. Engine first — exports pure functions imported by patches below
            'loyalty_points_manager/static/src/app/loyalty_earning_engine.js',
            # 2. Order earning patch (uses engine, patches PosOrder.pointsForPrograms)
            'loyalty_points_manager/static/src/app/order_model_patch.js',
            # 3. Orderline redemption patch (uses engine, patches PosOrderline + OrderSummary._setValue)
            'loyalty_points_manager/static/src/app/orderline_redemption_patch.js',
            # 3b. Unpaid-invoice guard (blocks redemption if customer has outstanding invoices)
            'loyalty_points_manager/static/src/app/unpaid_invoice_guard.js',
            # 3c. Popup fix — re-patches ControlButtons._applyReward to await async
            #     order._applyReward and show AlertDialog instead of silent toast
            'loyalty_points_manager/static/src/app/loyalty_block_popup.js',
            # 4. Widget getter (patches OrderSummary.prototype getters)
            'loyalty_points_manager/static/src/app/loyalty_points_widget.js',
            # 5. Template extension (references getters added by step 4)
            'loyalty_points_manager/static/src/app/loyalty_points_widget.xml',
            # 6. Post-payment loyalty popup — popup component must load before the patch
            'loyalty_points_manager/static/src/css/loyalty_popup.css',
            'loyalty_points_manager/static/src/app/loyalty_selection_popup.js',
            'loyalty_points_manager/static/src/app/loyalty_selection_popup.xml',
            # 7. PaymentScreen.validateOrder patch — loads after popup and all
            #    PosOrder patches so set_partner side-effects are fully installed
            'loyalty_points_manager/static/src/app/payment_screen_loyalty_patch.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
