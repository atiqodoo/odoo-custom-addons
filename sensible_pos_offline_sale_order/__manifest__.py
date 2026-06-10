# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
{
    'name': 'POS Offline Sale Order | POS Create Sale Order | POS Create Sale Order Offline',
    'version': '18.0.1.0',
    'summary': '''Enable Point of Sale (POS) users to create Sale Orders even when offline.''',
    'description': '''
    This module extends the functionality of Odoo's Point of Sale system by allowing users to create Sale Orders (SO) directly from the POS interface, even without an internet connection. Once the connection is restored, all offline-created Sale Orders are automatically synchronized with the backend.
    Key Features:

    Create Sale Orders from the POS interface.

    Offline support for order creation and storage.

    Automatic synchronization of orders when back online.

    Seamless integration with standard Odoo Sales and POS modules.

    Suitable for retail environments with intermittent or no connectivity.
    ''',
    'category': 'Sales/Point of Sale',
    'author': 'Sensible Consulting Services',
    'website': 'https://sensiblecs.com',
    'license': 'AGPL-3',
    'depends': ['pos_sale'],
    'data': [
        'views/sbl_res_config_settings_view.xml',
        'views/sbl_pos_config_view.xml'
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'sensible_pos_offline_sale_order/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'application': True,
    'installable': True,
}
