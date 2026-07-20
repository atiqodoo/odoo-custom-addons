{
    # POS Session Z-Report
    'name': 'POS Session Z-Report (XLSX)',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Export POS session control and profit summary as a Z-Report spreadsheet',
    'author': 'Custom',
    'depends': ['point_of_sale', 'pos_order_profit_wizard'],
    'data': [
        'security/ir.model.access.csv',
        'report/pos_session_z_report_pdf.xml',
        'report/pos_session_z_report_range_pdf.xml',
        'views/pos_session_z_report_wizard_views.xml',
        'views/pos_session_z_report_range_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'pos_session_z_report/static/src/cog_menu/z_report_summary_cog_item.js',
            'pos_session_z_report/static/src/cog_menu/z_report_summary_cog_item.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
