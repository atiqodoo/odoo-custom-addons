# -*- coding: utf-8 -*-
# POS Credit Note Gift Card — __manifest__.py
{
    'name': 'POS Credit Note Gift Card',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Issue gift-card credit notes from POS payment screen with smart return validation',
    'description': """
POS Credit Note Gift Card
=========================
Extends the Odoo 18 gift-card/e-wallet loyalty engine to expose a
**Credit Note** button directly on the POS payment screen.

Core features
-------------
* Credit Note button on the POS payment screen (refund orders only)
* Dynamically links to any configured gift-card loyalty program — not
  hard-coded to a single program
* Non-returnable product guard: products flagged as non-returnable
  (e.g. tinted paints) are blocked at the ticket-screen level before
  any refund is created
* Global discount adjustment: when the original order carried a global
  (order-level) discount, the credit note amount is adjusted according
  to the distribution method chosen in POS Settings (proportional,
  equal, or none)
* Commission adjustment: when pos_extra_amount_manager_extended has
  recorded TIER-1 extra-amount or TIER-2 base-profit distributions on
  the original order, the credit note can net out the relevant paid-
  out amounts before issuing the gift card
* Thermal POS receipt for the credit note — rendered by the OWL
  printer service, identical in format to a normal sale receipt
* HTTP controller for all backend gift-card operations, making the
  module easy to extend without touching models directly

Configuration (POS Settings)
-----------------------------
* Credit note gift-card program selection
* Global discount distribution method (proportional / equal / none)
* Commission netting mode (extra_amount / base_profit / both / none)
* Extra-amount distribution weight (0-100 %)
* Base-profit distribution weight (0-100 %)
* Require return reason before issuing credit note (optional)
    """,
    'author': 'Crown Kenya PLC',
    'website': 'https://www.crownpaints.co.ke',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'pos_loyalty',
        'account',
    ],
    # pos_extra_amount_manager_extended is declared as an optional dependency
    # (soft dep) — the module loads without it; commission features simply
    # remain disabled when it is absent.
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/pos_config_views.xml',
        'report/pos_credit_note_receipt.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_credit_note_gift_card/static/src/css/credit_note_button.css',
            'pos_credit_note_gift_card/static/src/js/credit_note_service.js',
            'pos_credit_note_gift_card/static/src/js/return_order_validator.js',
            'pos_credit_note_gift_card/static/src/js/ticket_screen_guard.js',
            'pos_credit_note_gift_card/static/src/js/payment_screen_credit_note.js',
            'pos_credit_note_gift_card/static/src/js/customer_account_return_guard.js',
            'pos_credit_note_gift_card/static/src/js/exchange_adjustment_guard.js',
            'pos_credit_note_gift_card/static/src/xml/credit_note_receipt.xml',
            'pos_credit_note_gift_card/static/src/xml/payment_screen_credit_note.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
