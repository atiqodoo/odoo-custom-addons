# -*- coding: utf-8 -*-
{
    'name': 'Paint Tinting Module',
    'version': '18.0.2.1.1',
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
        'stock_account',
        'mrp',
        'uom',
        'sale',  # ✅ ADDED: Required for quotation generation
        'sale_management',  # ✅ ADDED: For sale order management
        'sale_stock',  # Warehouse-aware real-time tinted stock confirmation guard
        'paint_colour_master',  # Existing colour/fandeck module
        'point_of_sale',
        'hr',
    ],
    'data': [
        # Security
        'security/formula_version_security.xml',
        'security/ir.model.access.csv',
        'security/formula_aps_access.xml',

        # Data
        'data/uom_data.xml',
        'data/product_category_data.xml',
        # 'data/colorant_products_data.xml',
        'data/deferred_valuation_sequence.xml',
        'data/pos_lot_cost_audit_sequence.xml',
        'data/tinted_mistake_sequence.xml',

        # Wizard Views
        'views/colorant_mapping_wizard_views.xml',
        'views/retint_wizard_views.xml',
        'views/tint_wizard_views.xml',
        'views/tint_product_exists_wizard_views.xml',
        'views/cost_comparison_wizard_views.xml',
        'views/quotation_generator_wizard_views.xml',
        'views/mrp_production_duplicate_wizard_views.xml',
        'views/formula_import_views.xml',
        'views/sale_order_views.xml',

        # Model Views
        'views/product_template_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/res_config_settings_views.xml',
        'views/tinting_formula_views.xml',
        'views/formula_version_views.xml',
        'views/formula_family_extension_views.xml',
        'views/formula_version_integration_views.xml',
        'views/formula_aps_views.xml',
        'views/tint_formula_search_views.xml',
        'views/tint_new_aps_formula_views.xml',
        'views/stock_deferred_valuation_views.xml',
        'views/tinted_mistake_views.xml',
        # 'views/retint_analytics_views.xml',
        # 'views/colour_code_views.xml',

        # Menu
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'paint_tinting/static/src/js/colorant_sort.js',
        ],
        'point_of_sale._assets_pos': [
            'paint_tinting/static/src/js/pos_sale_fix.js',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': ['openpyxl', 'xlsxwriter'],
    },
}
