# -*- coding: utf-8 -*-
{
    'name': 'Enhanced Stock Card Report (All Product Types)',
    'version': '18.0.1.1.2',
    'category': 'Inventory/Inventory',
    'summary': 'Comprehensive stock card - ACCEPTS ALL PRODUCT TYPES (storable, consumable, service)',
    'description': """
Enhanced Stock Card Report - ALL PRODUCT TYPES VERSION
=======================================================
Complete stock movement report with:
- **ACCEPTS ALL PRODUCT TYPES**: storable, consumable, service
- Physical IN/OUT/Balance quantities
- AVCO unit cost and inventory value (from stock.valuation.layer)
- Purchase amounts and unit prices (incl. VAT)
- POS amounts and unit prices (incl. taxes)
- Running totals for purchases and POS
- All move types: Purchase, Sales, POS, Manufacturing, Transfers, Adjustments
- Opening balance calculation
- PDF and Excel export
- 100% reconciliation with stock and accounting
- Debug features for troubleshooting

MODIFIED VERSION: Removed product type filter - now works with ALL product types!
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'stock',
        'stock_account',
        'purchase_stock',
        'sale_stock',
        'point_of_sale',
        'mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_card_wizard_views.xml',
        'views/menu_views.xml',
        'report/stock_card_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
