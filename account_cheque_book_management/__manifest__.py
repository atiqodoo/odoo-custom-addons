{
    'name': 'Cheque Book & Vendor Payments',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Physical cheque books, vendor payments, returns and replacements',
    'license': 'LGPL-3',
    'depends': ['account_check_printing', 'mail'],
    'data': [
        'security/security.xml', 'security/ir.model.access.csv',
        'views/cheque_views.xml', 'views/payment_views.xml', 'views/fee_views.xml', 'views/report_views.xml',
        'wizard/workflow_views.xml', 'views/evidence_views.xml', 'data/cron.xml',
    ],
    'application': True,
    'installable': True,
}
