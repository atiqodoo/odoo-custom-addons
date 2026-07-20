{
    'name': 'Stock Inventory Audit Log',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Read-only audit trail for physical inventory counts and validations',
    'depends': ['stock', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'views/stock_audit_log_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
