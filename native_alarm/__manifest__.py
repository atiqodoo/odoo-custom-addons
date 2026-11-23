{
    'name': 'Native Record Alarms',
    'version': '18.0.1.3.0',
    'summary': 'Date and time ringing alarms on native Odoo records and LAN PCs',
    'category': 'Productivity',
    'license': 'LGPL-3',
    'depends': ['mail', 'web'],
    'data': [
        'security/security.xml', 'security/ir.model.access.csv',
        'views/alarm_views.xml', 'views/settings_views.xml', 'views/sound_views.xml',
        'views/defaults_views.xml', 'data/activity.xml',
    ],
    'assets': {'web.assets_backend': ['native_alarm/static/src/alarm_service.js']},
    'application': True,
    'installable': True,
}
