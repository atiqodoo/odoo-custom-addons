{
    'name': 'Vendor Product Priority',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Primary/secondary vendor mapping and vendor-aware RFQ product search',
    'description': """
Vendor Product Priority
=======================
* Derives primary and secondary vendors from Purchase-tab vendor ordering.
* Keeps mappings variant-aware and company-aware without duplicating supplier data.
* Prioritizes mapped products in RFQ/LPO autocomplete, Search More, and Catalog.
* Preserves exact barcode/reference matches and leaves unmapped products available.
* Adds scoped backend and browser diagnostics for troubleshooting.
    """,
    'depends': [
        'purchase_product_matrix',
    ],
    'data': [
        'views/purchase_order_views.xml',
        'views/vendor_mapping_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'vendor_product_priority/static/src/js/vendor_priority_logger.js',
            'vendor_product_priority/static/src/js/purchase_product_field_patch.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}

