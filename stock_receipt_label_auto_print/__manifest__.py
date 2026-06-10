# -*- coding: utf-8 -*-
# Module: stock_receipt_label_auto_print
# Version: 18.0.1.0.0
#
# PURPOSE
# -------
# Adds an interactive label-printing popup that fires automatically when a
# purchase receipt (WH/IN) is validated.  The popup shows every product /
# lot that was actually received (done quantities only), lets the operator
# review and adjust how many labels to print, then delegates all rendering
# and IoT routing to Odoo 18's existing label pipeline
# (product.label.layout / lot.label.layout / stock.label_product_product).
#
# DESIGN PRINCIPLES
# -----------------
# * One override point only: stock.picking.button_validate()
# * All actual printing goes through the standard Odoo report/IoT chain —
#   no custom ESCPOS/ZPL code, no parallel printer registry.
# * Fully modular: the popup feature is opt-in per Operation Type.
# * Enhanced logging throughout (set log level DEBUG on
#   'stock_receipt_label_auto_print' to trace the full flow).
#
# COMPATIBILITY
# -------------
# Odoo 18 Community + Enterprise.
# IoT Box: works if the ir.actions.report records are linked to iot.device
# records via the standard Inventory > Configuration > Printers screen.
# Without IoT: falls back to browser PDF/ZPL download.
{
    'name': 'Barcode Label Print',
    'version': '18.0.1.0.0',
    'summary': 'Print 2-up 27mm product barcode labels and receipt labels',
    'category': 'Inventory/Inventory',
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',

    'depends': [
        'stock',    # stock.picking, stock.picking.type, product.label.layout
        'product',  # product.label.layout base wizard
        'product_barcode_custom',
    ],

    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_type_views.xml',
        'views/stock_receipt_label_wizard_views.xml',
        'views/product_barcode_print_wizard_views.xml',
        'views/barcode_label_config_views.xml',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,
}
