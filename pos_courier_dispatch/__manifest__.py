# -*- coding: utf-8 -*-
{
    'name': 'POS Courier Dispatch',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Manage courier dispatches for POS orders with tracking and accounting',
    'description': """
POS Courier Dispatch Management
================================

Features:
---------
* Register courier dispatches from POS orders
* Track courier information (name, phone, vehicle, reference)
* Manage payment responsibility (customer/company/shared)
* Automatic COGS accounting for company-paid courier fees
* Stock movement tracking (Shop → Courier Transit)
* Multi-state workflow (draft → in_transit → delivered → confirmed)
* Customer delivery confirmation
* Document and photo attachments
* Comprehensive reporting and analytics
* Partial dispatch support

Workflow:
---------
1. Complete POS sale (paid order)
2. Click "Dispatch via Courier" button
3. Fill courier details and payment terms
4. System creates dispatch record and moves stock
5. Track dispatch through states
6. Customer confirms receipt
7. Mark as done

Accounting:
-----------
* Company-paid courier fees posted to COGS
* Configurable journal and account
* Proper expense tracking

    """,
    'author': 'Crown Paints Kenya - ATIQ',
    'website': 'https://www.crownpaints.co.ke',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'stock',
        'account',
    ],
    'data': [
        # Security
        'security/courier_dispatch_security.xml',
        'security/ir.model.access.csv',
        
        # Data
        'data/ir_sequence.xml',
        'data/stock_location_data.xml',
        
        # Views
        'views/courier_dispatch_views.xml',
        'views/courier_company_views.xml',
        'views/pos_order_views.xml',
        
        # Wizards
        'wizard/register_courier_dispatch_wizard_views.xml',
        'wizard/confirm_delivery_wizard_views.xml',
        
        # Menu
        'views/menu.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
