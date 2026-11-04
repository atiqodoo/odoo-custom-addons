{
    'name': 'Purchase Variant Stock Compare',
    'version': '18.0.1.2.0',
    'category': 'Inventory/Purchase',
    'summary': 'Compare similar paint variants and available stock from RFQs',
    'license': 'LGPL-3',
    'depends': ['purchase_stock', 'purchase_net_price_compute', 'modern_quotation_catalogue', 'paint_colour_master'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'wizards/variant_stock_compare_views.xml',
        'views/purchase_order_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
}
