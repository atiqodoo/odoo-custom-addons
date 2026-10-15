# -*- coding: utf-8 -*-
{
    'name': 'Automatic Database Backup',
    'version': '1.0.0',
    'summary': 'Automatically create and manage database backups in Odoo',
    'description': """
    Automatic Database Backup Module
    ================================
    This module automates the process of creating database backups in Odoo.
    It allows you to:
    - Schedule automatic backups using cron jobs (daily, weekly, etc.)
    - Store backups locally or on remote storage (optional)
    - Download or delete backups from the UI
    - Get email or WhatsApp notifications for backup success or failure (optional)
        """,
    'category': 'Administration/Database',
    'author': 'CodeFusion OdooWorks',
    'website': 'https://codefusion-odooworks.odoo.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/mail_template_data.xml',
        'views/db_backup_configure_views.xml',
        'views/db_backup_history.xml',
        'views/db_backup_restore_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
