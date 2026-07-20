{
    'name': 'Vendor Department Contacts',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Manage vendor departments and department contacts from vendor profiles',
    'description': """
Vendor Department Contacts
==========================
Create structured vendor departments such as Sales, Marketing, or Dispatch
directly from the vendor profile. Each department can hold multiple contact
assignments linked to Contacts app records, with the contact title or role
used for that vendor department.

Technical design:
-----------------
* Vendor departments are separate records for easy extension by other apps.
* Contact assignments are separate relation records, allowing one contact to
  hold different titles in different departments or vendor contexts.
* Vendor form integration stays thin and inherits the standard partner form.
* Purchase menu actions expose the records for reporting and bulk maintenance.
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': [
        'contacts',
        'mail',
        'purchase',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/vendor_department_views.xml',
        'views/res_partner_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
