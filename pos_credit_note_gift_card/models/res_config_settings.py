# -*- coding: utf-8 -*-
"""
res_config_settings.py — Settings page relay
=============================================
Surfaces the ``pos.config`` credit-note fields on the standard
**Settings → Point of Sale** page by declaring ``related`` fields that
proxy through to the currently selected POS configuration.

No business logic lives here — all logic is in ``pos_config.py``.
"""

import logging
from odoo import models, fields

_logger = logging.getLogger('pos_credit_note_gift_card.res_config_settings')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # Credit-note gift-card program
    # -------------------------------------------------------------------------

    pos_credit_note_gift_card_program_id = fields.Many2one(
        comodel_name='loyalty.program',
        string='Credit Note Gift Card Program',
        related='pos_config_id.credit_note_gift_card_program_id',
        readonly=False,
        domain=[('program_type', '=', 'gift_card'), ('active', '=', True)],
        help='Gift-card program used to issue credit notes from the payment screen.',
    )

    # -------------------------------------------------------------------------
    # Global discount distribution
    # -------------------------------------------------------------------------

    pos_credit_note_discount_distribution = fields.Selection(
        related='pos_config_id.credit_note_discount_distribution',
        readonly=False,
        string='Return Discount Distribution',
    )

    # -------------------------------------------------------------------------
    # Commission netting
    # -------------------------------------------------------------------------

    pos_credit_note_commission_mode = fields.Selection(
        related='pos_config_id.credit_note_commission_mode',
        readonly=False,
        string='Commission Deduction Mode',
    )

    pos_credit_note_extra_weight = fields.Float(
        related='pos_config_id.credit_note_extra_weight',
        readonly=False,
        string='Extra-Amount Weight (%)',
    )

    pos_credit_note_base_weight = fields.Float(
        related='pos_config_id.credit_note_base_weight',
        readonly=False,
        string='Base-Profit Weight (%)',
    )

    # -------------------------------------------------------------------------
    # UX toggle
    # -------------------------------------------------------------------------

    pos_credit_note_require_reason = fields.Boolean(
        related='pos_config_id.credit_note_require_reason',
        readonly=False,
        string='Require Return Reason',
    )

    # -------------------------------------------------------------------------
    # Payment method for return order balancing
    # -------------------------------------------------------------------------

    pos_credit_note_payment_method_id = fields.Many2one(
        comodel_name='pos.payment.method',
        related='pos_config_id.credit_note_payment_method_id',
        readonly=False,
        string='Credit Note Payment Method',
        help='Payment method used to balance the return order when a credit note gift card is issued.',
    )
