# -*- coding: utf-8 -*-
{
    'name': 'Team Kubwa Cash-Out',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Controlled Crown Team Kubwa fundi cash-out workflow with receivable posting',
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'contacts',
        'mail',
        'point_of_sale',
        'pos_cod',
        'sensible_pos_access_rights_employee',
    ],
    'data': [
        'security/team_kubwa_groups.xml',
        'security/ir.model.access.csv',
        'data/team_kubwa_sequence.xml',
        'views/team_kubwa_policy_views.xml',
        'views/team_kubwa_cashout_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'team_kubwa_cashout/static/src/app/utils/team_kubwa_logger.js',
            'team_kubwa_cashout/static/src/app/patches/pos_store_patch.js',
            'team_kubwa_cashout/static/src/app/screens/cashout_screen/team_kubwa_cashout_screen.scss',
            'team_kubwa_cashout/static/src/app/screens/cashout_screen/TeamKubwaCashoutScreen.xml',
            'team_kubwa_cashout/static/src/app/screens/cashout_screen/TeamKubwaCashoutScreen.js',
            'team_kubwa_cashout/static/src/app/patches/team_kubwa_button.xml',
            'team_kubwa_cashout/static/src/app/patches/team_kubwa_button.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

