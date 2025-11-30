# -*- coding: utf-8 -*-
{
    'name': 'POS Deferred / Pending Collection (Backend Only)',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Track paid items left in store for later customer collection',
    'description': """
        POS Deferred / Pending Collection
        ==================================
        
        Allow customers to pay the full bill in POS, take some items immediately, 
        and leave the rest in the shop for later collection.
        
        Key Features:
        * 100% Backend operation (zero POS interface changes)
        * Track paid-but-not-collected items
        * Reserve pending items in inventory
        * Map items to original POS receipt and customer
        * Easy search & collection workflow
        * Printable labels for items left in store
        * Full reporting & aging analysis
        
        Perfect for paint retail & tinting stores where customers may need 
        multiple trips to collect large orders.
    """,
    'author': 'ATIQ - Crown Kenya PLC',
    'website': 'https://www.mzaramopaintsandwallpaper.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'point_of_sale',
        'stock',
        'product',
    ],
    'data': [
        'security/pending_collection_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/stock_location_data.xml',
        'views/paint_pending_collection_views.xml',
        'views/pos_order_views.xml',
        'wizard/register_deferred_collection_wizard_views.xml',
        'wizard/collect_pending_items_wizard_views.xml',
        'report/pending_collection_label_report.xml',
        'report/pending_collection_label_template.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
