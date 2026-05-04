# -*- coding: utf-8 -*-
"""
pos_blind_audit.models.pos_session
====================================
Extends ``pos.session`` with the blind-audit variance gate, the cash-out
withdrawal tracking, and the next-session opening-cash persistence.

Closing call chain (Odoo 18)
-----------------------------
Browser: ClosePosPopup.closeSession()  [JS]
  ├─ save_blind_cash_out()               RPC  ← NEW: saves cashier's withdrawal
  ├─ post_closing_cash_details()         RPC  → stores cash_register_balance_end_real
  ├─ update_closing_control_state_session() RPC
  └─ close_session_from_ui()             RPC  ← OVERRIDE 1
       ├─ _blind_audit_check()               ← variance gate (UserError caught here)
       ├─ super().close_session_from_ui()    ← accounting untouched
       └─ [on success] writes blind_cash_balance → pos.config.blind_audit_next_opening_cash

Defence-in-depth (backend closes)
----------------------------------
  _validate_session()                    ← OVERRIDE 2
       ├─ _blind_audit_check()               ← raises UserError if blocked
       └─ super()._validate_session()        ← accounting only reached if gate passes
            └─ _create_account_move()        ← NEVER modified

New fields
----------
``blind_cash_out``       Amount the cashier physically withdraws to the safe.
                         Sent from the browser via save_blind_cash_out() RPC.
``blind_cash_balance``   Computed: cash_register_balance_end_real - blind_cash_out.
                         Becomes pos.config.blind_audit_next_opening_cash on close.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_POS_MANAGER_GROUP = 'point_of_sale.group_pos_manager'


class PosSession(models.Model):
    """Extend pos.session with blind-audit enforcement and cash-out tracking."""

    _inherit = 'pos.session'

    # ------------------------------------------------------------------
    # New fields
    # ------------------------------------------------------------------

    blind_audit_override = fields.Boolean(
        string='Blind Audit Override',
        default=False,
        help=(
            "Set to True after 3 failed close attempts so the next "
            "close_session_from_ui call skips the variance gate. "
            "Written by log_blind_audit_attempt() before the browser "
            "calls closeSession() on the 4th attempt."
        ),
    )

    blind_cash_out = fields.Float(
        string='Cash Out (Blind Audit)',
        digits=(16, 2),
        default=0.0,
        help=(
            "Amount the cashier physically withdraws from the till at closing "
            "(e.g. taken to the safe).  Set via the browser RPC "
            "save_blind_cash_out() before the session is closed.  "
            "Does not create any accounting entry."
        ),
    )

    blind_cash_balance = fields.Float(
        string='Cash Balance (Blind Audit)',
        digits=(16, 2),
        compute='_compute_blind_cash_balance',
        store=True,
        help=(
            "Cash physically remaining in the till after the cashier's "
            "withdrawal: cash_register_balance_end_real − blind_cash_out.  "
            "Written to pos.config.blind_audit_next_opening_cash on a "
            "successful blind-audit close so the next session can use it "
            "as its pre-populated opening float."
        ),
    )

    # ------------------------------------------------------------------
    # Computed field
    # ------------------------------------------------------------------

    @api.depends('cash_register_balance_end_real', 'blind_cash_out')
    def _compute_blind_cash_balance(self):
        for rec in self:
            rec.blind_cash_balance = (
                rec.cash_register_balance_end_real - rec.blind_cash_out
            )

    # ------------------------------------------------------------------
    # RPC method called by the browser
    # ------------------------------------------------------------------

    def log_blind_audit_attempt(
        self,
        attempt_number,
        counted_amount=0.0,
        cash_out=0.0,
        discrepancy=0.0,
        outcome='blocked',
    ):
        """Create an audit-trail record for a failed (or override) close attempt.

        Called from the browser each time the cashier's discrepancy check fires.
        Uses ``sudo()`` so the cashier's session user does not need direct model
        access on ``pos.blind.audit.attempt``.

        Parameters
        ----------
        attempt_number : int
            Sequential count of attempts in this session (1, 2, 3).
        counted_amount : float
            Amount the cashier typed into the Cash Count field.
        cash_out : float
            Amount the cashier entered in the Cash Out field.
        discrepancy : float
            Absolute difference between counted and expected.
        outcome : str
            ``'blocked'`` or ``'override'`` (3rd attempt auto-allowed).
        """
        self.ensure_one()

        _logger.info(
            "[pos_blind_audit] log_blind_audit_attempt | session='%s' | "
            "cashier='%s' | attempt=%d | counted=%.2f | cash_out=%.2f | "
            "discrepancy=%.2f | outcome=%s",
            self.name,
            self.env.user.login,
            attempt_number,
            counted_amount,
            cash_out,
            discrepancy,
            outcome,
        )

        if outcome == 'override':
            # Allow the next close_session_from_ui to bypass _blind_audit_check.
            # This must be committed BEFORE the browser calls closeSession().
            # The browser awaits this RPC on the override attempt so the flag
            # is guaranteed to be in the DB before close_session_from_ui runs.
            self.write({'blind_audit_override': True})

        self.env['pos.blind.audit.attempt'].sudo().create({
            'session_id': self.id,
            'config_id': self.config_id.id,
            'cashier_id': self.env.user.id,
            'attempt_number': attempt_number,
            'counted_amount': float(counted_amount or 0.0),
            'expected_amount': self.cash_register_balance_end,
            'cash_out': float(cash_out or 0.0),
            'discrepancy': float(discrepancy or 0.0),
            'variance_limit': self.config_id.variance_amount,
            'outcome': outcome,
            'timestamp': fields.Datetime.now(),
        })
        return True

    def save_blind_cash_out(self, cash_out):
        """Persist the cashier's cash-out withdrawal amount before session close.

        Called by the browser patch (close_pos_popup_patch.js) as the very
        first step inside closeSession(), before post_closing_cash_details()
        and close_session_from_ui() are called.

        This ordering guarantees that when close_session_from_ui() runs:
        1. ``blind_cash_out`` is already saved on the record.
        2. ``blind_cash_balance`` (computed) reflects the correct value.
        3. The value can be written to pos.config immediately after close.

        Parameters
        ----------
        cash_out : float
            Amount the cashier is withdrawing from the till.  Clamped to
            [0, ∞) server-side for safety.

        Returns
        -------
        bool
            Always True (caller can ignore the return value).
        """
        self.ensure_one()
        cash_out = max(0.0, float(cash_out or 0.0))

        _logger.info(
            "[pos_blind_audit] save_blind_cash_out | session='%s' | "
            "user='%s' | cash_out=%.2f",
            self.name,
            self.env.user.login,
            cash_out,
        )

        self.write({'blind_cash_out': cash_out})
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _blind_audit_check(self):
        """Validate the cashier's cash count is within the configured variance.

        Raises
        ------
        odoo.exceptions.UserError
            When blind audit is on, cash control is active, the discrepancy
            exceeds ``variance_amount``, AND the current user is not a POS
            manager.

        Returns
        -------
        None
        """
        self.ensure_one()
        config = self.config_id

        if self.blind_audit_override:
            _logger.warning(
                "[pos_blind_audit] _blind_audit_check | session='%s' | "
                "blind_audit_override=True — skipping variance gate (3-attempt override).",
                self.name,
            )
            return

        if not config.limit_variance:
            _logger.debug(
                "[pos_blind_audit] _blind_audit_check | session='%s' | "
                "limit_variance=False → skipping.",
                self.name,
            )
            return

        if not config.cash_control:
            _logger.debug(
                "[pos_blind_audit] _blind_audit_check | session='%s' | "
                "cash_control=False → no cash register, skipping.",
                self.name,
            )
            return

        counted = self.cash_register_balance_end_real
        expected = self.cash_register_balance_end
        difference = abs(counted - expected)
        variance_limit = config.variance_amount
        is_manager = self.env.user.has_group(_POS_MANAGER_GROUP)

        _logger.info(
            "[pos_blind_audit] _blind_audit_check | session='%s' | "
            "user='%s' | is_manager=%s | "
            "counted=%.2f | expected=%.2f | difference=%.2f | "
            "variance_limit=%.2f | blind_cash_out=%.2f | blind_cash_balance=%.2f",
            self.name,
            self.env.user.login,
            is_manager,
            counted,
            expected,
            difference,
            variance_limit,
            self.blind_cash_out,
            self.blind_cash_balance,
        )

        if difference > variance_limit:
            _logger.warning(
                "[pos_blind_audit] BLOCKED | session='%s' | "
                "user='%s' | is_manager=%s | difference=%.2f exceeds limit=%.2f.",
                self.name,
                self.env.user.login,
                is_manager,
                difference,
                variance_limit,
            )
            raise UserError(_(
                "Discrepancy too high. Recount cash.\n\n"
                "Counted: %(counted).2f   "
                "Expected: %(expected).2f   "
                "Difference: %(diff).2f   "
                "Allowed: %(limit).2f",
                counted=counted,
                expected=expected,
                diff=difference,
                limit=variance_limit,
            ))
        else:
            _logger.info(
                "[pos_blind_audit] PASSED | session='%s' | "
                "difference=%.2f within limit=%.2f — proceeding.",
                self.name,
                difference,
                variance_limit,
            )

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def action_pos_session_open(self):
        """Override: pre-populate opening cash from blind_audit_next_opening_cash.

        Odoo's default sets ``cash_register_balance_start`` from the previous
        session's ``cash_register_balance_end_real`` (the full counted amount).
        When blind audit is active, we want the opening cash to be the balance
        that was intentionally left in the till (counted − cash_out), which was
        saved to ``pos.config.blind_audit_next_opening_cash`` on the previous
        session's close.
        """
        result = super().action_pos_session_open()

        for session in self.filtered(lambda s: s.state == 'opening_control' and not s.rescue):
            config = session.config_id
            if not (config.limit_variance and config.cash_control):
                continue
            next_opening = config.blind_audit_next_opening_cash
            if not next_opening:
                continue
            _logger.info(
                "[pos_blind_audit] action_pos_session_open | session='%s' | "
                "overriding opening cash: %.2f → %.2f (blind_audit_next_opening_cash)",
                session.name,
                session.cash_register_balance_start,
                next_opening,
            )
            session.cash_register_balance_start = next_opening

        return result

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        """Primary UI close path — returns structured error on blind-audit failure.

        Sequence
        --------
        1. Run ``_blind_audit_check()``.  If it raises UserError, convert to a
           structured ``{'successful': False, ...}`` dict the JS can display as
           a cashier-friendly dialog.
        2. Capture ``blind_cash_out`` before delegating (field inaccessible after
           session closes).
        3. Delegate to super() — all standard accounting logic unchanged.
        4. On success:
           a. Write ``blind_cash_balance`` to ``pos.config.blind_audit_next_opening_cash``
              so the next session can pre-populate its opening cash control prompt.
           b. If ``blind_cash_out > 0``, create an ``account.bank.statement.line``
              for the cashier's withdrawal.  The ORM auto-posts the move:
                  Credit → cash journal default account (e.g. 125001 Cash FROM POS)
                  Debit  → journal suspense account     (e.g. 120002 Bank Suspense)
              Using a statement line (not a bare ``account.move``) is required
              so the entry registers in the bank reconciliation engine and
              increments the "N to reconcile" counter on the accounting dashboard
              — identical behaviour to standard POS Cash Out.
              ``try_cash_in_out`` is NOT used: it hard-requires
              ``extras['translatedType']`` (KeyError on empty dict) and is
              designed for mid-session use only.  We build the vals directly.
        """
        self.ensure_one()
        config = self.config_id  # capture before session state changes

        _logger.info(
            "[pos_blind_audit] close_session_from_ui | session='%s' | "
            "limit_variance=%s | cash_control=%s | "
            "blind_cash_out=%.2f | blind_cash_balance=%.2f",
            self.name,
            config.limit_variance,
            config.cash_control,
            self.blind_cash_out,
            self.blind_cash_balance,
        )

        # ── Blind audit variance gate ─────────────────────────────────
        try:
            self._blind_audit_check()
        except UserError as exc:
            error_message = exc.args[0] if exc.args else _("Discrepancy too high. Recount cash.")
            _logger.warning(
                "[pos_blind_audit] close_session_from_ui BLOCKED | "
                "session='%s' | returning structured error to JS.",
                self.name,
            )
            return {
                'successful': False,
                'title': _("Cash Count Error"),
                'message': error_message,
                'open_order_ids': [],
            }
        # ─────────────────────────────────────────────────────────────

        # Capture before super() — session fields may be inaccessible after close.
        _blind_cash_out_amount = self.blind_cash_out

        _logger.debug(
            "[pos_blind_audit] close_session_from_ui | session='%s' | "
            "blind audit gate cleared | blind_cash_out=%.2f | "
            "delegating to super().close_session_from_ui().",
            self.name,
            _blind_cash_out_amount,
        )
        result = super().close_session_from_ui(bank_payment_method_diff_pairs)

        # ── On success: persist opening cash + post blind cash-out GL entry ──
        if (
            isinstance(result, dict)
            and result.get('successful')
            and config.limit_variance
            and config.cash_control
        ):
            # ── Persist cash balance for next session opening ─────────
            balance = self.blind_cash_balance
            _logger.info(
                "[pos_blind_audit] close_session_from_ui | session='%s' | "
                "writing blind_cash_balance=%.2f to pos.config '%s' "
                "as next opening amount.",
                self.name,
                balance,
                config.name,
            )
            config.sudo().write({'blind_audit_next_opening_cash': balance})

            # ── Blind cash-out → bank statement line ──────────────────
            # Created AFTER session closes successfully so it can never
            # block the close or leave orphan entries on a failed close.
            #
            # Why account.bank.statement.line and NOT account.move directly:
            #   A direct account.move posts to the GL but is invisible to
            #   the bank reconciliation engine — the "N to reconcile" counter
            #   on the accounting dashboard never fires for it.
            #   account.bank.statement.line.create() does both in one step:
            #     1. Auto-creates and posts the account.move with correct lines:
            #           Credit → cash journal default account  (125001 Cash FROM POS)
            #           Debit  → journal suspense account      (120002 Bank Suspense)
            #     2. Registers the line for bank reconciliation — identical
            #        behaviour to standard POS Cash Out (try_cash_in_out).
            #
            # Why NOT try_cash_in_out():
            #   It hard-requires extras['translatedType'] in payment_ref
            #   construction (KeyError on empty dict) and is designed for
            #   mid-session use; calling it in closing_control state is unsafe.
            #   We build the vals directly — same effect, no hidden dependency.
            if _blind_cash_out_amount > 0.0:
                _cash_journal = self.cash_journal_id

                _logger.debug(
                    "[pos_blind_audit] close_session_from_ui | session='%s' | "
                    "blind cash-out statement line: "
                    "cash_journal='%s' (id=%d) | amount=%.2f (negative=out)",
                    self.name,
                    _cash_journal.name, _cash_journal.id,
                    _blind_cash_out_amount,
                )

                if not _cash_journal:
                    _logger.warning(
                        "[pos_blind_audit] close_session_from_ui | session='%s' | "
                        "blind cash-out statement line SKIPPED: no cash_journal_id "
                        "on session — manual journal entry required: "
                        "Credit <cash account> %.2f / Debit <suspense account> %.2f",
                        self.name,
                        _blind_cash_out_amount,
                        _blind_cash_out_amount,
                    )
                else:
                    _stmt_ref = _("Blind Audit Cash Out - %s") % self.name
                    _stmt_vals = {
                        'journal_id': _cash_journal.id,
                        'amount': -_blind_cash_out_amount,   # negative → cash out
                        'date': fields.Date.context_today(self),
                        'payment_ref': _stmt_ref,
                        'pos_session_id': self.id,
                    }
                    _logger.info(
                        "[pos_blind_audit] close_session_from_ui | session='%s' | "
                        "creating blind cash-out bank statement line | "
                        "amount=%.2f (stored as %.2f) | payment_ref='%s' | "
                        "journal='%s' (id=%d) | pos_session_id=%d",
                        self.name,
                        _blind_cash_out_amount,
                        -_blind_cash_out_amount,
                        _stmt_ref,
                        _cash_journal.name, _cash_journal.id,
                        self.id,
                    )
                    try:
                        stmt_line = self.env['account.bank.statement.line'].sudo().create(_stmt_vals)
                        _logger.info(
                            "[pos_blind_audit] close_session_from_ui | session='%s' | "
                            "blind cash-out bank statement line created successfully | "
                            "stmt_line_id=%d | move='%s' (id=%d) | amount=%.2f | "
                            "reconciliation triggered on journal='%s'",
                            self.name,
                            stmt_line.id,
                            stmt_line.move_id.name if stmt_line.move_id else 'N/A',
                            stmt_line.move_id.id if stmt_line.move_id else 0,
                            _blind_cash_out_amount,
                            _cash_journal.name,
                        )
                    except Exception as exc:
                        _logger.error(
                            "[pos_blind_audit] close_session_from_ui | session='%s' | "
                            "FAILED to create blind cash-out bank statement line | "
                            "amount=%.2f | error=%s | "
                            "manual journal entry required: "
                            "Credit <cash account> %.2f / Debit <suspense account> %.2f",
                            self.name,
                            _blind_cash_out_amount,
                            exc,
                            _blind_cash_out_amount,
                            _blind_cash_out_amount,
                        )
                        raise
            else:
                _logger.debug(
                    "[pos_blind_audit] close_session_from_ui | session='%s' | "
                    "skipping blind cash-out statement line: "
                    "blind_cash_out=%.2f (zero).",
                    self.name,
                    _blind_cash_out_amount,
                )
            # ─────────────────────────────────────────────────────────
        # ─────────────────────────────────────────────────────────────────

        return result

    def _validate_session(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        """Defence-in-depth gate: blocks accounting entries on blind-audit failure.

        Fires BEFORE ``super()._validate_session()`` → BEFORE
        ``_create_account_move()`` is called.  No journal entries, no partial
        commits if the check raises.
        """
        _logger.debug(
            "[pos_blind_audit] _validate_session | session='%s' | "
            "limit_variance=%s | variance_amount=%.2f | cash_control=%s",
            self.name,
            self.config_id.limit_variance,
            self.config_id.variance_amount,
            self.config_id.cash_control,
        )

        self._blind_audit_check()

        _logger.debug(
            "[pos_blind_audit] _validate_session gate cleared for session='%s'.",
            self.name,
        )

        return super()._validate_session(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )
