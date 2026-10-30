{
    'name': 'Document Source Links',
    'version': '18.0.1.0.0',
    'summary': 'Extensible, access-controlled source navigation for Odoo forms',
    'license': 'LGPL-3',
    'depends': ['web'],
    'assets': {'web.assets_backend': [
        'document_source_links/static/src/source_links.js',
        'document_source_links/static/src/source_links.xml',
    ]},
    'installable': True,
}
