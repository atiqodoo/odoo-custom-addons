# Part of custom addons.
{
    'name': 'POS Fixed Amount Discount',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Adds fixed-amount mode to the POS Global Discount button',
    'depends': ['pos_discount'],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_fixed_discount/static/src/**/*',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
