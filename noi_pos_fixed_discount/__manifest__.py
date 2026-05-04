{
    'name': 'POS Fixed Discount',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Allow fixed amount discount on POS order lines',
    'description': """
        This module adds the ability to apply a fixed discount amount 
        on POS order lines instead of only percentage-based discounts.
    """,
    "author": "NexOrioins Techsphere",
    "maintainer": "Rowan Ember",
    "website": "nexorionis.odoo.com",
    "support": "nexorionis.info@gmail.com",
    "images": ["static/description/banner.jpg"],
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [
        'views/pos_order_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'noi_pos_fixed_discount/static/src/**/*',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
