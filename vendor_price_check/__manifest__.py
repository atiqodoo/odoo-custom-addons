{
    'name': 'Vendor Price Check',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Check vendor bill prices against historical data',
    'description': """
        Vendor Bill Price Validation
        =============================
        - Compares vendor bill prices against historical data
        - Flags discrepancies when prices differ from both lowest and average
        - Requires approval from designated user before posting
        - Tracks all price discrepancies for audit purposes
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': [
        'purchase',
        'account',
        'purchase_net_price_compute',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/purchase_order_views.xml',
        'views/purchase_order_action.xml', 
        'views/res_config_settings_views.xml',
        'views/vendor_price_discrepancy_views.xml',
        'views/vendor_price_wizard_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}