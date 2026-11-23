# -*- coding: utf-8 -*-
{
    "name": "POS Auto Variant Price Rounding",
    "version": "18.0.2.0.0",
    "category": "Point of Sale",
    "summary": "Automatically increase POS selling prices when variant inclusive cost rises",
    "depends": [
        "point_of_sale",
        "stock_account",
        "stock_landed_costs",
        "mail",
        "purchase_stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/price_rules.xml",
        "views/pos_auto_price_log_views.xml",
        "views/product_product_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_auto_variant_price_rounding/static/src/price_sync.js",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
