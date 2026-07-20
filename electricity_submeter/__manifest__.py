{
    'name': 'Electricity Sub-Meter Invoicing',
    'version': '18.0.1.0.0',
    'summary': 'Track electricity sub-meter readings and automate customer invoicing for neighbors.',
    'description': """
This module allows paint retail stores (or any business) to:
- Track sub-meters associated with neighbors/customers.
- Log periodic readings (previous and current) per sub-meter.
- Calculate consumed units (kWh) and allow editable rate overrides.
- Automatically calculate untaxed receivable amount, VAT, and total amount.
- Generate draft Odoo customer invoices mapping to configured journals and accounts.
- Fully compatible with Odoo 18 Accounting (Anglo-Saxon, AVCO costing, and Automatic Inventory Valuation).
    """,
    'category': 'Accounting',
    'author': 'Antigravity',
    'website': 'https://www.odoo.com',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/electricity_meter_views.xml',
        'views/electricity_reading_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
