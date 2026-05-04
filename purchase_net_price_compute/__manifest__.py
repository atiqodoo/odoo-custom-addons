{
    'name': 'Purchase Net Price Compute',
    'version': '1.0',
    'depends': ['purchase', 'account', 'product'],
    'data': [
        'views/product_vendor_pricing_views.xml',  # Load this FIRST
        'views/res_partner_views.xml',
        'views/product_template_views.xml',
        'views/purchase_order_views.xml',
        'views/account_move_views.xml',
    ],
}