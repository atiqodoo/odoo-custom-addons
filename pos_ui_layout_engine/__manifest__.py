# -*- coding: utf-8 -*-
{
    "name": "POS UI Layout Engine",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Configurable POS layout, density, typography, and flex ratios",
    "author": "Custom Development",
    "depends": ["point_of_sale", "pos_direct_thermal_printer"],
    "data": [
        "views/pos_settings_view.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "pos_ui_layout_engine/static/src/js/color_picker_field.js",
            "pos_ui_layout_engine/static/src/xml/color_picker_field.xml",
            "pos_ui_layout_engine/static/src/scss/color_picker_field.scss",
        ],
        "point_of_sale._assets_pos": [
            "pos_ui_layout_engine/static/src/js/pos_data_loader.js",
            "pos_ui_layout_engine/static/src/js/product_screen_patch.js",
            "pos_ui_layout_engine/static/src/js/product_sales_sort_patch.js",
            "pos_ui_layout_engine/static/src/xml/product_screen.xml",
            "pos_ui_layout_engine/static/src/xml/navbar.xml",
            "pos_ui_layout_engine/static/src/scss/pos_ui.scss",
        ],
    },
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
