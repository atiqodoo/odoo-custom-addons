# -*- coding: utf-8 -*-
{
    'name': 'Modern Quotation Catalogue',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Modern realtime quotation workspace using standard Odoo sales logic',
    'description': """
Modern Quotation Catalogue
==========================

Standalone quotation workspace that creates and edits normal Odoo quotations
while preserving existing sale, stock, pricing, tax and tinting logic.
    """,
    'author': 'Crown Kenya PLC',
    'depends': [
        'sale_management',
        'sale_stock',
        'stock',
        'product',
        'account',
        'paint_colour_master',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/modern_quotation_views.xml',
        'views/category_group_views.xml',
        'views/colour_attribute_group_views.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'modern_quotation_catalogue/static/src/js/modern_quotation_workspace.js',
            'modern_quotation_catalogue/static/src/xml/modern_quotation_workspace.xml',
            'modern_quotation_catalogue/static/src/scss/modern_quotation_workspace.scss',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
