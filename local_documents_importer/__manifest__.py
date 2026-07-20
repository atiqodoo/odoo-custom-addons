# -*- coding: utf-8 -*-
{
    'name': 'Local Documents Importer',
    'version': '18.0.1.0.0',
    'category': 'Documents',
    'summary': 'Import local Windows folder files into Odoo Documents',
    'description': """
Local Documents Importer
========================

Lightweight cron-based importer for scanner, WhatsApp, and email download
folders. Maps configured local Windows source roots into Odoo Documents
folders, auto-creates nested Odoo folders, and imports files through the
native documents/attachment filestore flow.
    """,
    'author': 'Crown Kenya PLC',
    'depends': [
        'documents',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/local_document_import_log_views.xml',
        'views/local_document_watch_path_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
