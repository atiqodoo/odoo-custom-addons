{
    'name': 'POS Cost Price Validation',
    'version': '18.0.1.0.9',
    'category': 'Point of Sale',
    'summary': 'Prevent selling products below VAT-inclusive cost price',
    'depends': ['point_of_sale', 'stock_account'],
    'data': [
      
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'custom_pos_cost_validation/static/src/js/pos_cost_validation.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}