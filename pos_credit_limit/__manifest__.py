# -*- coding: utf-8 -*-
# Custom POS Credit Limit Control
# Blocks / manages Customer Account payment via three validation gates:
#   Gate 1 - customer must have property_payment_term_id (live check)
#   Gate 2 - True Balance + amount must not exceed credit_limit
#             Handles: deposit path, partial credit, full block
#   Gate 3 - real-time RPC fetches live balance before Gates 1/2 run
#
# Additional features:
#   Issue 1 - Deposit path: allow purchase up to deposit balance when credit_limit=0
#   Issue 2 - Partial credit: let cashier charge available credit, pay rest by other method
#   Issue 3 - Double-count fix: terminal-state filter in calculateUnsyncedAmount
#   Issue 4 - Session payments: session_incoming_payments subtracted from True Balance
#   Issue 5 - Return guard: block Customer Account on returns where original had no customer
#
# ACCOUNTING SAFETY: This module creates NO journal entries and does NOT
# modify account.move, account.move.line, or any transactional accounting model.
# It is a READ-ONLY validation layer on top of the POS payment screen.
{
    'name': 'POS Credit Limit Control',
    'version': '18.0.2.0.0',
    'category': 'Point of Sale',
    'summary': 'Customer Account payment gates: terms, credit limit, deposits, partial pay, returns',
    'author': 'Custom Development',
    'depends': ['point_of_sale', 'account'],
    'data': [
        'views/pos_payment_method_view.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            # Layer 0 — Dialog UI (no business-logic imports)
            # Gate 1: no payment terms
            'pos_credit_limit/static/src/app/dialogs/no_payment_terms_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/no_payment_terms_popup.js',
            # Gate 2: credit limit exceeded (full block)
            'pos_credit_limit/static/src/app/dialogs/credit_limit_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/credit_limit_popup.js',
            # Issue 1: customer has a deposit (informational confirm)
            'pos_credit_limit/static/src/app/dialogs/deposit_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/deposit_popup.js',
            # Issue 2: partial credit available
            'pos_credit_limit/static/src/app/dialogs/partial_credit_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/partial_credit_popup.js',
            # Issue 5: return on account blocked
            'pos_credit_limit/static/src/app/dialogs/return_blocked_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/return_blocked_popup.js',
            # Gate 1.5: overdue invoices block
            'pos_credit_limit/static/src/app/dialogs/overdue_invoices_popup.xml',
            'pos_credit_limit/static/src/app/dialogs/overdue_invoices_popup.js',
            # Layer 1 — Pure calculation (no OWL / store dependencies)
            'pos_credit_limit/static/src/app/calculators/true_balance_calculator.js',
            # Layer 2 — Gate validators (depend on Layer 0 + Layer 1 only)
            'pos_credit_limit/static/src/app/validators/payment_terms_validator.js',
            'pos_credit_limit/static/src/app/validators/credit_limit_validator.js',
            # Layer 3 — Store patch (adds RPC helper to PosStore)
            'pos_credit_limit/static/src/app/store/pos_store_patch.js',
            # Layer 4 — Component patch (orchestrator, depends on all above)
            'pos_credit_limit/static/src/app/payment_screen/payment_screen_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
