# Powered by Sensible Consulting Services
# -*- coding: utf-8 -*-
# © 2025 Sensible Consulting Services (<https://sensiblecs.com/>)
{
    'name': 'POS Access Rights Employee | Point of Sale Access Rights for Employees | Point of Sale Employee Access Management | POS Cashier Access Control | Point of Sale Cashier Permissions',
    'version': '18.0.1.2',
    'summary': '''The POS Employee Access Rights module enhances control over the POS interface by allowing 
        administrators to enable or disable key functionalities for each cashier. 
        It simplifies the management of multiple cashiers and ensures that POS operations are restricted based on user roles and responsibilities.
    ''',
    'description': '''
        Order Management Controls:
        ==========================
        Hide or Show the New Order button.
        Hide or Show the Delete Order option.
        Hide or Show the Customer Selection button.
        Hide or Show the Actions button.
        Hide or Show the Payment button.

        Configurable Access Permissions:
        ==============================
        Hide or Show the Numpad.
        Enable or Disable the Plus-Minus buttons in the Numpad.
        Enable or Disable the Quantity (QTY) button in the Numpad.
        Enable or Disable the Discount button.
        Enable or Disable the Change Price option.
    ''',
    'category': 'Sales/Point of Sale',
    'author': 'Sensible Consulting Services',
    'website': 'https://sensiblecs.com',
    'license': 'AGPL-3',
    'depends': [
        'pos_hr',
        'pos_fixed_discount',
        'pos_cod',
        'pos_loyalty',
        'pos_settle_due',
        'mpesa_c2b_sms',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sbl_app_gate_data.xml',
        'views/sbl_app_gate_config_views.xml',
        'views/sbl_app_gate_log_views.xml',
        'views/sbl_hr_employee_view.xml',
        'views/sbl_hr_employee_mpesa_expiry_view.xml',
        'views/sbl_hr_employee_cod_payment_method_view.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'sensible_pos_access_rights_employee/static/src/authorization/**/*',
            'sensible_pos_access_rights_employee/static/src/overrides/**/*',
        ],
        'web.assets_backend': [
            # M-Pesa gate loads first — app_gate wraps it to avoid double prompts.
            'sensible_pos_access_rights_employee/static/lib/backend/mpesa_sms_app_gate.js',
            'sensible_pos_access_rights_employee/static/lib/backend/app_gate/app_gate_service.js',
        ],
    },
    'images': ['static/description/banner.png'],
    'application': True,
    'installable': True,
}
