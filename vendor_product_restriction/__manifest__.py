# -*- coding: utf-8 -*-
{
    'name': 'Vendor Product Restriction with Override',
    'version': '18.0.1.0.0',
    'category': 'Purchase',
    'summary': 'Restrict product selection based on vendor mapping with override group',
    'description': """
Vendor Product Restriction Module
==================================

Features:
---------
* Restricts product selection on RFQs based on vendor-product mapping
* Security group "Purchase: Vendor Restriction Override" for bypassing restrictions
* Automatic assignment of override group to administrators
* Clear warning messages when users try to select unmapped products
* Shows alternative vendors for products not mapped to selected vendor
* Seamless integration with existing purchase workflows

User Experience:
----------------
* Restricted users: Can only select products mapped to the chosen vendor
* Override users: Can select any purchasable product regardless of vendor
* Informative warnings when attempting to select unmapped products
* Suggestions for alternative vendors when available

Technical Details:
------------------
* Dynamic domain filtering on purchase.order.line.product_id
* Onchange validation with explicit user feedback
* Line-level vendor synchronization from order header
* Compatible with custom pricing and vendor bill workflows
* Odoo 18 compliant (list views, no deprecated attributes)

Integration:
------------
* Compatible with purchase_net_price_compute module
* Compatible with vendor_price_check wizard
* No conflicts with custom pricing logic
* Preserves standard Odoo purchase functionality
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'purchase',
        'purchase_stock',
    ],
    'data': [
        'security/security_groups.xml',
        'views/purchase_order_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0.00,
    'currency': 'USD',
}