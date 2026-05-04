{
    'name': 'Paint Colour Master',
    'version': '1.0',
    'summary': 'Manage paint colour fandecks and codes for products',
    'description': 'This module allows users to manage paint colour fandecks and codes, integrating with product templates.',
    'category': 'Inventory',
    'depends': ['product', 'base','point_of_sale','sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/colour_fandeck_view.xml',
        'views/colour_code_view.xml',
        'views/product_template_view.xml',
        'views/menu_view.xml',
        'views/product_template_pos_view.xml',
        
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
