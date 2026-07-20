# -*- coding: utf-8 -*-
{
    "name": "POS Order Profit Wizard",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Edit POS order quantities/prices and preview VAT-inclusive profit",
    "author": "Custom Development",
    "depends": ["point_of_sale", "pos_ui_layout_engine", "pos_extra_amount_manager_extended", "pos_cod", "sale", "sale_margin"],
    "data": [
        "views/pos_order_profit_tab_views.xml",
        "views/pos_order_list_profit_views.xml",
        "views/sale_order_profit_tab_views.xml",
        "views/pos_session_profit_summary_views.xml",
        "views/pos_session_list_profit_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_order_profit_wizard/static/src/app/components/profit_wizard/profit_wizard.js",
            "pos_order_profit_wizard/static/src/app/control_buttons/profit_button.js",
            "pos_order_profit_wizard/static/src/app/components/profit_wizard/profit_wizard.xml",
            "pos_order_profit_wizard/static/src/app/control_buttons/profit_button.xml",
            "pos_order_profit_wizard/static/src/app/components/profit_wizard/profit_wizard.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
