{
    'name': 'Purchase Overdue Receipt Follow-up',
    'version': '18.0.2.1.1',
    'category': 'Inventory/Purchase',
    'summary': 'Working-time overdue receipt warnings and controlled replacement RFQs',
    'license': 'LGPL-3',
    'depends': ['purchase_variant_stock_compare', 'resource', 'mail'],
    'data': [
        'security/ir.model.access.csv', 'security/security.xml',
        'data/receiving_calendar.xml', 'data/ir_cron.xml',
        'wizards/replacement_rfq_views.xml',
        'views/receipt_followup_views.xml', 'views/res_config_settings_views.xml',
        'views/purchase_order_views.xml',
        'views/vendor_delivery_policy_views.xml', 'views/purchase_delivery_views.xml',
    ],
    'assets': {'web.assets_backend': [
        'purchase_overdue_receipt_followup/static/src/js/overdue_warning_service.js',
    ]},
    'installable': True,
}
