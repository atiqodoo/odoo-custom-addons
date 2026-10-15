# -*- coding: utf-8 -*-
{
    'name': 'Virtual Quotation Print',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Printable virtual quotations without creating operational sale orders',
    'description': """
Virtual Quotation Print
=======================

Create editable print-only quotations that can be linked to customers and
optional real Odoo quotations without triggering sale, stock, delivery or
manufacturing operations.
    """,
    'author': 'Crown Kenya PLC',
    'depends': [
        'account',
        'sale_management',
        'modern_quotation_catalogue',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'report/virtual_quotation_report.xml',
        'views/virtual_quotation_views.xml',
        'views/virtual_quotation_import_wizard_views.xml',
        'views/virtual_quotation_discount_wizard_views.xml',
        'views/sale_order_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'virtual_quotation_print/static/src/js/virtual_section_subtotal.js',
        ],
    },
    'application': False,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
