# -*- coding: utf-8 -*-
"""
pos_blind_audit.models.pos_config
==================================
Extends ``pos.config`` with fields that drive the blind-audit behaviour at
POS session closing.

Field summary
-------------
``limit_variance`` (Boolean)
    Master switch.  When True the ClosePosPopup JS component hides the
    expected-cash total, the difference row, and the auto-fill button so the
    cashier counts blind.  The server-side gate in ``pos.session`` is also
    activated.

``variance_amount`` (Float)
    Monetary threshold (company currency).  Non-manager cashiers whose counted
    cash differs from the expected balance by more than this amount are blocked
    from closing the session.

``blind_audit_next_opening_cash`` (Float)
    Written by ``pos.session.close_session_from_ui`` at the end of a
    blind-audit closing sequence.  Stores the cash balance that remains in
    the till after the cashier's Cash Out withdrawal (= counted − cash_out).
    The next session can use this as its pre-populated opening float.

Data-loading note
-----------------
``pos.config`` uses ``_load_pos_data_fields = []`` which causes Odoo's
``search_read`` to return *all* readable fields.  All three fields are
therefore automatically included in the POS bootstrap payload — no extra
loader override is required.
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    """Extend pos.config with blind-audit configuration and state fields."""

    _inherit = 'pos.config'

    # ------------------------------------------------------------------
    # Blind audit fields
    # ------------------------------------------------------------------

    limit_variance = fields.Boolean(
        string='Enable Blind Audit',
        default=False,
        help=(
            "When enabled, cashiers see only the 'Cash Count' input during "
            "session closing — the expected cash total, the difference figures, "
            "and the auto-fill button are hidden from the browser.  "
            "The server validates the variance and blocks non-manager users "
            "if the discrepancy exceeds 'Maximum Variance Amount'."
        ),
    )

    variance_amount = fields.Float(
        string='Maximum Variance Amount',
        digits=(16, 2),
        default=0.0,
        help=(
            "Maximum absolute difference (company currency) allowed between "
            "the cashier's counted cash and the session's expected closing "
            "balance when blind audit is active.  "
            "Users NOT in the POS Manager group who exceed this threshold are "
            "blocked from closing the session.  "
            "Managers can always close regardless of the variance.  "
            "Set to 0.00 to require an exact match."
        ),
    )

    blind_audit_next_opening_cash = fields.Float(
        string='Next Session Opening Cash',
        digits=(16, 2),
        default=0.0,
        help=(
            "Automatically set at the end of each blind-audit session close.  "
            "Holds the cash that the cashier physically left in the till "
            "(= counted cash − cash out withdrawal).  "
            "Can be used to pre-populate the opening cash control prompt for "
            "the next session.  Not written by any accounting entry."
        ),
    )

    default_next_opening_cash = fields.Float(
        string='Default Cash Balance (Next Opening)',
        digits=(16, 2),
        default=0.0,
        help=(
            "Target float amount the manager wants left in the till after each "
            "session close.  When set and blind audit is active, the POS "
            "closing popup auto-computes the Cash Out field as:\n\n"
            "    Cash Out = Cash Count − Default Cash Balance\n\n"
            "The cashier can still edit the Cash Out field manually.  "
            "Leave at 0.00 to disable auto-computation and require manual entry."
        ),
    )

    # ------------------------------------------------------------------
    # Override write for debug visibility
    # ------------------------------------------------------------------

    def write(self, vals):
        """Log blind-audit field changes at DEBUG level for traceability."""
        _blind_audit_keys = {
            'limit_variance',
            'variance_amount',
            'blind_audit_next_opening_cash',
            'default_next_opening_cash',
        }
        if _blind_audit_keys & set(vals.keys()):
            for record in self:
                _logger.debug(
                    "[pos_blind_audit] pos.config '%s' (id=%d) blind-audit "
                    "fields updated: %s",
                    record.name,
                    record.id,
                    {k: v for k, v in vals.items() if k in _blind_audit_keys},
                )
        return super().write(vals)
