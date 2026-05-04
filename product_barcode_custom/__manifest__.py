{
    'name': 'Product Barcode Enhancement',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Enhances product barcode generation with modular structure and bulk processing',
    'depends': ['product'],
    'data': [
        'views/product_product_views.xml',
        'views/barcode_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}