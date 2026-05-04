# -*- coding: utf-8 -*-
# pos_blind_audit – Odoo 18 Point of Sale Blind Audit module.
# Depends: point_of_sale, pos_hr (pos_hr compatibility patches are included)
# Hides expected cash / difference from cashiers; server enforces variance gate.
{
    'name': 'POS Blind Audit',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Enforce blind cash audit at POS session closing with configurable variance control',
    'description': """
POS Blind Audit
===============
Adds a configurable blind-audit closing workflow to Point of Sale sessions.

Features
--------
* **Blind counting** – The ClosePosPopup hides the expected-cash total and
  the difference column, so cashiers count without cognitive bias.
* **Variance gate** – On session close, the server compares the cashier's
  count against the session's expected balance.  Non-manager users are
  blocked with a clear error when the discrepancy exceeds the configured
  ``Maximum Variance Amount``.
* **Manager override** – Users in the ``point_of_sale.group_pos_manager``
  group can always close regardless of the variance.
* **Accounting untouched** – The block fires before ``_create_account_move``
  so no journal entries are created for a rejected session.

Configuration
-------------
Go to *Point of Sale > Configuration > Settings* (or the POS config form)
and enable **Blind Audit** under the closing-control block.  Set
**Maximum Variance Amount** to the largest discrepancy you will allow.
    """,
    'author': '',
    'depends': ['point_of_sale', 'pos_hr'],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_config_views.xml',
        'views/pos_blind_audit_attempt_views.xml',
    ],
    'assets': {
        # Loaded into the POS browser application bundle
        'point_of_sale._assets_pos': [
            'pos_blind_audit/static/src/js/close_pos_popup_patch.js',
            'pos_blind_audit/static/src/xml/close_pos_popup.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
