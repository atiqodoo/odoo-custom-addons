# -*- coding: utf-8 -*-

{
    'name': 'POS - Disable PDF Invoice Download',
    'category': 'Point of Sale',
    'summary': 'This module allows you to enable or disable the automatic download of PDF invoices in the POS.',
    'description': "Adds a setting in the POS configuration to control whether PDF invoices can be downloaded after order validation.",
    'author': 'Dustin Mimbela',
    'version': '1.0',
    'depends': ['point_of_sale', 'account'],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_disable_invoice_download/static/src/**/*'
        ],
    },
    'data':  ['views/pos.xml'],
    'installable': True,
    'auto_install': False,
    "license": "LGPL-3",
    "images":["static/description/banner.png"],
}
