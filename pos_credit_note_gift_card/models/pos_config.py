# -*- coding: utf-8 -*-
"""
pos_config.py — POS configuration extension
============================================
Stores all credit-note/gift-card module settings **per POS terminal**
on ``pos.config``.  ``res.config.settings`` merely relays these fields
so they appear on the standard Settings page.

Settings exposed
----------------
credit_note_gift_card_program_id
    The ``loyalty.program`` (program_type = 'gift_card') that will be
    used when issuing a credit note.  Must be active and configured with
    the standard gift-card rule/reward pair.

credit_note_discount_distribution
    How a global line-level discount on the original order should be
    reflected in the credit note amount:
      * 'proportional' — each return line is reduced by its own discount %
      * 'equal'        — total order discount is split equally across lines
      * 'none'         — discount is ignored; refund at full original price

credit_note_commission_mode
    Which commission tiers to net out from the credit note when
    pos_extra_amount_manager_extended is installed:
      * 'none'         — do not deduct any commission
      * 'extra_amount' — deduct only TIER-1 extra-amount distributions
      * 'base_profit'  — deduct only TIER-2 base-profit distributions
      * 'both'         — deduct both tiers

credit_note_extra_weight / credit_note_base_weight
    Percentage weight (0-100) of each commission tier that should be
    charged back to the returning customer.  This lets managers decide
    that e.g. only 50 % of the commission is deducted on a return.

credit_note_require_reason
    When True the cashier must enter a free-text return reason before
    the Credit Note button becomes active in the payment screen.

Logging
-------
Logger: ``pos_credit_note_gift_card.pos_config``
Level  : DEBUG for routine reads, WARNING for misconfigured programs.
"""

import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger('pos_credit_note_gift_card.pos_config')

# ---------------------------------------------------------------------------
# Constants — selection values
# ---------------------------------------------------------------------------
DISCOUNT_DISTRIBUTION_SELECTION = [
    ('proportional', 'Proportional (per-line discount %)'),
    ('equal',        'Equal split across returned lines'),
    ('none',         'None — refund at full original price'),
]

COMMISSION_MODE_SELECTION = [
    ('none',         'None — do not deduct commission'),
    ('extra_amount', 'Deduct TIER-1 Extra Amount only'),
    ('base_profit',  'Deduct TIER-2 Base Profit only'),
    ('both',         'Deduct both tiers (Extra + Base Profit)'),
]


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # -------------------------------------------------------------------------
    # Gift-card program selection
    # -------------------------------------------------------------------------

    credit_note_gift_card_program_id = fields.Many2one(
        comodel_name='loyalty.program',
        string='Credit Note Gift Card Program',
        domain=[('program_type', '=', 'gift_card'), ('active', '=', True)],
        help=(
            'Select the gift-card loyalty program that will be used to '
            'generate credit notes in the POS payment screen.  The program '
            'must be a standard Odoo gift-card program (1 point per currency, '
            '1 currency per point reward).'
        ),
    )

    # -------------------------------------------------------------------------
    # Global discount handling
    # -------------------------------------------------------------------------

    credit_note_discount_distribution = fields.Selection(
        selection=DISCOUNT_DISTRIBUTION_SELECTION,
        string='Return Discount Distribution',
        default='proportional',
        required=True,
        help=(
            'Controls how a global line-level discount on the original '
            'sale order is handled when computing the credit note amount.\n\n'
            '• Proportional: each returned line is reduced by its own '
            'recorded discount percentage — the most accurate method.\n'
            '• Equal: the total order discount is divided equally across '
            'all returned lines — simpler but less precise.\n'
            '• None: the full original price is credited back regardless '
            'of any discount.'
        ),
    )

    # -------------------------------------------------------------------------
    # Commission netting (pos_extra_amount_manager_extended)
    # -------------------------------------------------------------------------

    credit_note_commission_mode = fields.Selection(
        selection=COMMISSION_MODE_SELECTION,
        string='Commission Deduction Mode',
        default='none',
        required=True,
        help=(
            'When pos_extra_amount_manager_extended is installed and '
            'commissions were distributed on the original order, this '
            'setting controls which commission tiers are netted out of '
            'the credit note amount.'
        ),
    )

    credit_note_extra_weight = fields.Float(
        string='Extra-Amount Commission Weight (%)',
        default=100.0,
        digits=(5, 2),
        help=(
            'Percentage of the TIER-1 extra-amount commission to deduct '
            'from the credit note.  Range: 0–100.  '
            'Set to 50 to charge back only half the commission.'
        ),
    )

    credit_note_base_weight = fields.Float(
        string='Base-Profit Commission Weight (%)',
        default=100.0,
        digits=(5, 2),
        help=(
            'Percentage of the TIER-2 base-profit commission to deduct '
            'from the credit note.  Range: 0–100.'
        ),
    )

    # -------------------------------------------------------------------------
    # UX options
    # -------------------------------------------------------------------------

    credit_note_require_reason = fields.Boolean(
        string='Require Return Reason',
        default=False,
        help=(
            'When enabled, the cashier must type a reason for the return '
            'before the Credit Note button is activated in the payment screen.'
        ),
    )

    # -------------------------------------------------------------------------
    # Payment method used to balance the return order
    # -------------------------------------------------------------------------

    credit_note_payment_method_id = fields.Many2one(
        comodel_name='pos.payment.method',
        string='Credit Note Payment Method',
        help=(
            'The POS payment method used to balance the return order when '
            'a credit note gift card is issued.  '
            'Create a dedicated payment method: '
            'Accounting → Configuration → Journals → New → Type: Cash → Name "Credit Note Gift Card". '
            'Then POS → Configuration → Payment Methods → New → link to that journal. '
            'Add the payment method to this POS terminal (Payment tab) and select it here.'
        ),
    )

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    @api.constrains('credit_note_extra_weight', 'credit_note_base_weight')
    def _check_commission_weights(self):
        for cfg in self:
            for fname, label in [
                ('credit_note_extra_weight', 'Extra-Amount Weight'),
                ('credit_note_base_weight',  'Base-Profit Weight'),
            ]:
                val = getattr(cfg, fname)
                if not (0.0 <= val <= 100.0):
                    raise ValidationError(
                        f"POS '{cfg.name}': {label} must be between 0 and 100 "
                        f"(got {val:.2f})."
                    )

    # -------------------------------------------------------------------------
    # NOTE: _load_pos_data_fields is intentionally NOT overridden here.
    #
    # pos.config loads its data via search_read(domain, fields=[], load=False)
    # (the base pos.load.mixin returns [] which means "all fields").  All
    # fields declared on pos.config — including the credit-note ones above —
    # are therefore included automatically in the POS session payload without
    # any extra wiring.
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Helper — validate that the selected program is properly configured
    # -------------------------------------------------------------------------

    def _validate_credit_note_program(self):
        """
        Verify that ``credit_note_gift_card_program_id`` meets the
        standard Odoo gift-card structural requirements.

        Returns (True, '') on success or (False, error_message) on failure.
        Called by the controller before issuing a credit note.
        """
        self.ensure_one()
        program = self.credit_note_gift_card_program_id

        _logger.debug(
            "[PosConfig][_validate_credit_note_program] config='%s' "
            "program='%s' (id=%s)",
            self.name,
            program.name if program else 'None',
            program.id if program else 'N/A',
        )

        if not program:
            msg = (
                f"POS '{self.name}': No credit-note gift-card program configured. "
                "Please set one in POS Settings → Credit Note."
            )
            _logger.warning("[PosConfig][_validate_credit_note_program] %s", msg)
            return False, msg

        if program.program_type != 'gift_card':
            msg = (
                f"Program '{program.name}' is not a gift-card program "
                f"(type: {program.program_type})."
            )
            _logger.warning("[PosConfig][_validate_credit_note_program] %s", msg)
            return False, msg

        if not program.active:
            msg = f"Gift-card program '{program.name}' is archived/inactive."
            _logger.warning("[PosConfig][_validate_credit_note_program] %s", msg)
            return False, msg

        _logger.debug(
            "[PosConfig][_validate_credit_note_program] "
            "Program '%s' passed validation.", program.name,
        )
        return True, ''
