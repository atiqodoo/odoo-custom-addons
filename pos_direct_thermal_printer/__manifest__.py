# -*- coding: utf-8 -*-
{
    "name": "POS Direct Thermal Printer",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Direct ESC/POS thermal receipt printing from POS validation",
    "author": "Custom Development",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/pos_config_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_direct_thermal_printer/static/src/app/constants.js",
            "pos_direct_thermal_printer/static/src/app/logger.js",
            "pos_direct_thermal_printer/static/src/app/services/receipt_builder.js",
            "pos_direct_thermal_printer/static/src/app/services/escpos_encoder.js",
            "pos_direct_thermal_printer/static/src/app/transports/odoo_server_windows_transport.js",
            "pos_direct_thermal_printer/static/src/app/transports/local_bridge_transport.js",
            "pos_direct_thermal_printer/static/src/app/transports/web_serial_transport.js",
            "pos_direct_thermal_printer/static/src/app/services/direct_printer_service.js",
            "pos_direct_thermal_printer/static/src/app/services/cod_dispatch_receipt_builder.js",
            "pos_direct_thermal_printer/static/src/app/services/cod_dispatch_printer_service.js",
            "pos_direct_thermal_printer/static/src/app/cod_dispatch_print_listener.js",
            "pos_direct_thermal_printer/static/src/app/payment_screen/payment_screen_patch.js",
        ],
    },
    "installable": True,
    "application": False,
}
