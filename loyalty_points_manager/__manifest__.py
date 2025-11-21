# -*- coding: utf-8 -*-
{
    'name': 'Loyalty Points Manager',
    'version': '18.0.1.0.0',
    'category': 'Sales',
    'summary': 'Manual management of customer loyalty points with accounting integration',
    'description': """
        Loyalty Points Manager
        ======================
        This module allows manual management of customer loyalty points:
        * Add or reduce loyalty points manually
        * Wizard interface with customer search
        * Real-time balance calculation
        * Full accounting integration
        * Audit trail for all point adjustments
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'contacts',
        'loyalty',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/loyalty_points_adjustment_views.xml',
        'wizard/loyalty_points_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
