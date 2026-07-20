{
    'name': 'Purchase Net Price Compute',
    'version': '18.0.2.3.0',
    'depends': [
        'purchase_stock',
        'account',
        'product',
        'product_movement_volume_analysis',
        'vendor_department_contacts',
    ],
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_config_settings_attachment_requirement_views.xml',
        'views/product_vendor_pricing_views.xml',  # Load this FIRST
        'views/res_partner_views.xml',
        'views/vendor_invoice_profile_views.xml',
        'views/res_users_views.xml',
        'views/product_template_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_order_attachment_requirement_views.xml',
        'views/purchase_order_attachment_preview_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_picking_attachment_requirement_views.xml',
        'views/stock_picking_attachment_preview_views.xml',
        'views/account_move_attachment_requirement_views.xml',
        'views/account_move_views.xml',
        'reports/purchase_lpo_report_templates.xml',
    ],
}
