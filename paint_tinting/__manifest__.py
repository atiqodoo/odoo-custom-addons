# -*- coding: utf-8 -*-
{
    'name': 'Paint Tinting Module',
    'version': '18.0.1.0.1',
    'category': 'Manufacturing',
    'summary': 'Custom paint tinting module with LargoTint integration for Crown Kenya PLC',
    'description': """
        Paint Tinting Module for Odoo 18
        =================================
        
        Features:
        ---------
        * Dynamic tinted product creation
        * Persistent BOM management with versioning
        * 16 pre-loaded colorants with shot-to-ml conversion
        * Variant-based base paint selection
        * VAT-inclusive and exclusive costing
        * Negative stock support with warnings
        * Full integration with paint_colour_master module
        * AVCO costing method
        * Custom Volume UoM (1L, 4L, 20L)
        * Cost comparison across different brands
        * Volume scaling for formula translation
        * Quotation generation with manual pricing
        * Cost integrity checker for margin protection
    """,
    'author': 'Crown Kenya PLC',
    'website': 'https://www.crownpaints.co.ke',
    'depends': [
        'base',
        'product',
        'stock',
        'mrp',
        'uom',
        'sale',  # ✅ ADDED: Required for quotation generation
        'sale_management',  # ✅ ADDED: For sale order management
        'paint_colour_master',  # Existing colour/fandeck module
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',

        # Data
        'data/uom_data.xml',
        'data/product_category_data.xml',
        # 'data/colorant_products_data.xml',
        'data/deferred_valuation_sequence.xml',

        # Wizard Views
        'views/colorant_mapping_wizard_views.xml',
        'views/retint_wizard_views.xml',
        'views/tint_wizard_views.xml',
        'views/cost_comparison_wizard_views.xml',
        'views/quotation_generator_wizard_views.xml',
        'views/mrp_production_duplicate_wizard_views.xml',
        'views/sale_order_views.xml',

        # Model Views
        'views/product_template_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/tinting_formula_views.xml',
        'views/stock_deferred_valuation_views.xml',
        # 'views/retint_analytics_views.xml',
        # 'views/colour_code_views.xml',

        # Menu
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}