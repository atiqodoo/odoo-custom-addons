# -*- coding: utf-8 -*-
{
    'name': 'POS Deferred / Pending Collection (Backend Only)',
    'version': '18.0.1.0.1',   # bumped from 18.0.1.0.0 to trigger pre-migrate script
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

        v18.0.1.0.1 Changes:
        * Fix: Lot/Serial Number now correctly passed to return stock move
          for lot-tracked tinted products (resolves collection wizard error).
        * Fix: Stale list view for register.deferred.collection.wizard removed
          via pre-migration script (resolves ParseError on upgrade).
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
    "data": [
        "data/sequence_data.xml",
        "data/stock_location_data.xml",
        "security/ir.model.access.csv",
        "security/pending_collection_security.xml",
        "views/menu_views.xml",
        "views/paint_pending_collection_views.xml",
        "views/pos_order_views.xml",
        "views/register_deferred_collection_wizard_views.xml",
        "report/pending_collection_label_report.xml",
        "report/pending_collection_label_template.xml",
        "wizard/collect_pending_items_wizard_views.xml",
        "wizard/register_deferred_collection_wizard_views.xml"
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}