{
    'name': 'Vendor Payment Auditing',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Policy-driven vendor bill variance auditing and payment blocking',
    'description': """
Vendor Payment Auditing
=======================
Centralizes vendor bill variance findings, vendor-specific blocking policies,
resolution requirements, and payment guards for posted vendor bills.
    """,
    'depends': [
        'account',
        'mail',
        'purchase',
    ],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/audit_variance_types.xml',
        'views/vendor_payment_audit_policy_views.xml',
        'views/vendor_payment_audit_case_views.xml',
        'views/vendor_payment_audit_finding_views.xml',
        'views/res_partner_views.xml',
        'views/account_move_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
