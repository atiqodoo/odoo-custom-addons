{
    'name': 'POS Custom Receipt Product Name',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Display a custom product name on POS receipts only, without changing the cart or search',
    'author': 'Custom',
    'depends': ['point_of_sale'],
    'data': [
        'views/product_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_custom_receipt_name/static/src/js/pos_order_patch.js',
            'pos_custom_receipt_name/static/src/xml/orderline_patch.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
