{
    'name': 'Product Barcode Enhancement',
    'version': '1.1',
    'category': 'Inventory',
    'summary': 'Adds secondary Nexx ERP barcode per product variant with POS scanning and bulk CSV import',
    'depends': ['product', 'point_of_sale', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/barcode_rules.xml',
        'views/res_config_settings_views.xml',
        'views/product_product_views.xml',
        'views/product_template_views.xml',
        'views/barcode_wizard_views.xml',
        'views/nexx_barcode_import_wizard_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'product_barcode_custom/static/src/js/nexx_barcode_pos.js',
        ],
    },
    'installable': True,
    'application': False,
}
