# -*- coding: utf-8 -*-
{
    "name": "POS Auto Variant Price Rounding",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Automatically increase POS selling prices when variant inclusive cost rises",
    "depends": [
        "point_of_sale",
        "stock_account",
        "stock_landed_costs",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_auto_price_log_views.xml",
        "views/product_product_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
