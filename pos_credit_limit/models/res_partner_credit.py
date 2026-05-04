# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartnerCredit(models.Model):
    # Responsibility: exposes a single RPC endpoint used by Gate 3 (Real-Time Sync).
    #
    # Returns five financial figures the POS frontend needs for all three gates:
    #   total_due                — partner.credit (live; positive = owes us)
    #   deposit_balance          — max(0, -total_due); non-zero when partner.credit < 0
    #   credit_limit             — configured credit ceiling (pos.credit_limit field)
    #   session_incoming_payments— cash/card payments received from this customer in
    #                              currently open POS sessions, not yet posted to
    #                              accounting (Issue 4: session payments not reflected)
    #   payment_term_id          — live company-context payment term (Gate 1)
    #   payment_term_name        — term name for logging
    #
    # Issue 1 (deposits): deposit_balance lets the POS allow purchases up to the
    #   deposit amount even when credit_limit = 0.
    #
    # Issue 4 (session payments not reflected): session_incoming_payments subtracts
    #   account-settlement payments made in open sessions from the True Balance,
    #   because these payments reduce the partner's balance but are not yet posted.
    #   We identify settlement orders as completed POS orders with NO product lines
    #   (Settle Account creates orders with no goods, only a payment).
    #
    # KEY DESIGN NOTE — company_dependent field context:
    #   property_payment_term_id is a company_dependent (ir.property) field.
    #   Its value depends on which company is active in self.env.
    #   We must call partner.with_company(company_id) before reading it.
    #
    # ACCOUNTING SAFETY:
    #   This class is READ-ONLY. It does not write to account.move,
    #   account.move.line, account.journal, or any transactional model.
    _inherit = 'res.partner'

    @api.model
    def get_credit_info(self, partner_id, company_id=False):
        """Gate 3 RPC endpoint — returns live credit figures for a partner.

        Called from pos_store_patch.js every time the cashier taps the
        Customer Account payment button.

        Args:
            partner_id (int): res.partner primary key from the POS frontend.
            company_id (int|False): The POS session company ID. Used to set
                the correct company context when reading company_dependent
                fields like property_payment_term_id. Without this, a
                multi-company user may read the wrong company's value.

        Returns:
            dict:
                error                    (bool)  — True only if partner not found
                total_due                (float) — outstanding receivable balance
                deposit_balance          (float) — prepaid deposit (0 if no deposit)
                credit_limit             (float) — configured POS credit ceiling
                session_incoming_payments(float) — unposted account-settlement payments
                partner_name             (str)   — display name for popup messages
                payment_term_id          (int|False) — account.payment.term ID or False
                payment_term_name        (str)   — term name for logging
        """
        partner = self.browse(partner_id)

        if not partner.exists():
            _logger.warning(
                "PCL get_credit_info: partner_id=%s not found in database", partner_id
            )
            return {
                'error':                     True,
                'total_due':                 0.0,
                'deposit_balance':           0.0,
                'credit_limit':              0.0,
                'session_incoming_payments': 0.0,
                'partner_name':              '',
                'payment_term_id':           False,
                'payment_term_name':         '',
            }

        commercial = partner.commercial_partner_id

        # ── Company context for company_dependent fields ──────────────────────
        # property_payment_term_id and credit_limit are stored per-company via ir.property.
        # We must read them in the POS session's company context.
        if company_id:
            partner_ctx    = partner.with_company(company_id)
            commercial_ctx = commercial.with_company(company_id)
        else:
            partner_ctx    = partner
            commercial_ctx = commercial

        # ── Payment term: check contact first, then commercial parent ─────────
        # Contacts may have their own payment term stored on their own record.
        payment_term = (
            partner_ctx.property_payment_term_id
            or commercial_ctx.property_payment_term_id
        )

        # ── total_due and deposit_balance (Issue 1) ───────────────────────────
        # partner.credit = sum of all unpaid receivable move lines for this partner.
        # Positive → customer owes us money.
        # Negative → customer has a prepaid deposit / overpayment on their account.
        total_due = float(commercial.credit)
        deposit_balance = max(0.0, -total_due)

        # ── Session incoming payments (Issue 4) ───────────────────────────────
        # When a customer pays their balance at POS (Settle Account), that payment
        # is NOT posted to accounting until the session closes.
        # We query completed POS orders in open sessions for this partner that have
        # NO product lines — these are account-settlement orders.
        # Their non-credit payment amounts reduce the True Balance.
        session_incoming = self._pcl_get_session_incoming_payments(
            commercial, company_id
        )

        # ── Diagnostic logging — always visible in Odoo server log ───────────
        _logger.warning(
            "PCL get_credit_info\n"
            "  partner        : %s (id=%s)\n"
            "  company_id     : %s (env.company=%s)\n"
            "  payment_term   : %s\n"
            "  total_due      : %.2f\n"
            "  deposit_balance: %.2f\n"
            "  credit_limit   : %.2f\n"
            "  session_incoming: %.2f",
            partner.name, partner_id,
            company_id, self.env.company.name,
            payment_term.name if payment_term else 'NONE',
            total_due,
            deposit_balance,
            float(commercial_ctx.credit_limit),
            session_incoming,
        )

        # ── Overdue invoice check (Gate 1.5) ─────────────────────────────────
        # Pass session_incoming so that same-session settle payments are deducted
        # from the overdue total before deciding whether to block.
        # Invoices where invoice_date_due < today and payment_state is not_paid/partial.
        overdue_info = self._pcl_get_overdue_info(commercial, company_id, session_incoming)

        return {
            'error':                     False,
            'total_due':                 total_due,
            'deposit_balance':           deposit_balance,
            'credit_limit':              float(commercial_ctx.credit_limit),
            'session_incoming_payments': session_incoming,
            'partner_name':              partner.name,
            'payment_term_id':           payment_term.id if payment_term else False,
            'payment_term_name':         payment_term.name if payment_term else '',
            'has_overdue':               overdue_info['has_overdue'],
            'overdue_amount':            overdue_info['overdue_amount'],
            'overdue_invoice_count':     overdue_info['overdue_invoice_count'],
            'oldest_overdue_date':       overdue_info['oldest_overdue_date'],
        }

    def _pcl_get_session_incoming_payments(self, commercial_partner, company_id=False):
        """Sum cash/card payments received from the customer in currently open
        POS sessions that have NOT yet been posted to accounting.

        Issue 4 fix: The customer's partner.credit is updated only when the POS
        session closes and journal entries are posted. Within an open session,
        a cashier who accepts cash toward a customer's balance will see the old
        (higher) credit figure from the Gate 3 RPC. This method returns the
        total of those unposted payments so the True Balance formula can subtract
        them: trueBalance = backendTotalDue + unsyncedCharges - sessionIncoming.

        Identification of settlement orders:
            Odoo POS "Settle Account" orders have NO product lines (order.lines
            is empty). They exist purely to record the incoming payment against
            the customer's receivable. We filter on this characteristic.

        Args:
            commercial_partner (res.partner): The top-level commercial partner.
            company_id (int|False): POS session company for filtering.

        Returns:
            float: Total incoming payments (≥ 0)
        """
        try:
            # Build domain for open POS sessions
            session_domain = [('state', '=', 'opened')]
            if company_id:
                session_domain.append(('company_id', '=', company_id))

            open_sessions = self.env['pos.session'].search(session_domain)

            if not open_sessions:
                return 0.0

            # Find completed orders for this partner in those sessions
            completed_orders = self.env['pos.order'].search([
                ('session_id', 'in', open_sessions.ids),
                ('partner_id', '=', commercial_partner.id),
                ('state', 'in', ['paid', 'done', 'invoiced']),
            ])

            if not completed_orders:
                return 0.0

            # Settlement orders have NO product lines.
            # Regular sales have product lines; we must NOT count those
            # (a customer paying by cash for goods is NOT reducing their credit balance).
            settlement_orders = completed_orders.filtered(lambda o: not o.lines)

            if not settlement_orders:
                _logger.warning(
                    "PCL _pcl_get_session_incoming | partner=%s | open sessions=%s"
                    " | completed orders=%s | settlement orders=0 (none found)",
                    commercial_partner.name,
                    len(open_sessions),
                    len(completed_orders),
                )
                return 0.0

            # Sum non-credit payment method amounts on settlement orders.
            # (Credit method payments on a settlement order would be unusual but
            # we exclude them to avoid counting outbound credit as incoming cash.)
            incoming_total = 0.0
            for order in settlement_orders:
                for payment in order.payment_ids:
                    if not payment.payment_method_id.pcl_is_credit_method:
                        incoming_total += payment.amount

            incoming_total = max(0.0, round(incoming_total, 2))

            _logger.warning(
                "PCL _pcl_get_session_incoming | partner=%s | open sessions=%s"
                " | completed orders=%s | settlement orders=%s | incoming_total=%.2f",
                commercial_partner.name,
                len(open_sessions),
                len(completed_orders),
                len(settlement_orders),
                incoming_total,
            )

            return incoming_total

        except Exception as exc:
            # Never let a session-payment query failure block Gate 3.
            # Log and return 0 (conservative — slightly over-reports True Balance).
            _logger.error(
                "PCL _pcl_get_session_incoming FAILED for partner %s: %s",
                commercial_partner.name, exc
            )
            return 0.0

    def _pcl_get_overdue_info(self, commercial_partner, company_id=False, session_incoming=0.0):
        """Check whether the partner has any overdue unpaid invoices,
        taking into account same-session settlement payments not yet posted.

        Gate 1.5: If any posted invoice has invoice_date_due < today and is
        not fully paid, Customer Account credit is blocked regardless of
        available credit headroom — UNLESS session_incoming payments made in
        the current POS session already cover the full overdue balance.

        Same-session deposit handling:
            When a customer pays their overdue invoices via POS Settle Account
            in the same session, account.move still shows payment_state as
            'not_paid'/'partial' (the journal entry is only posted on session
            close). We subtract session_incoming from the raw overdue_amount.
            If effective_overdue ≤ 0, the block is lifted for this session.

        Args:
            commercial_partner (res.partner): Top-level commercial partner.
            company_id (int|False): POS session company for filtering.
            session_incoming (float): Cash/card payments received from this
                customer in the current open session (from
                _pcl_get_session_incoming_payments). Used to offset the
                raw accounting overdue amount.

        Returns:
            dict:
                has_overdue          (bool)  — True if net overdue > 0
                overdue_amount       (float) — Net overdue after session payments
                overdue_invoice_count(int)   — Number of overdue invoices (accounting)
                oldest_overdue_date  (str)   — Oldest invoice_date_due as "YYYY-MM-DD"
        """
        _EMPTY = {
            'has_overdue':           False,
            'overdue_amount':        0.0,
            'overdue_invoice_count': 0,
            'oldest_overdue_date':   '',
        }
        try:
            today = fields.Date.context_today(self)

            domain = [
                ('partner_id', 'child_of', commercial_partner.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('invoice_date_due', '<', today),
            ]
            if company_id:
                domain.append(('company_id', '=', company_id))

            overdue = self.env['account.move'].search(domain)

            if not overdue:
                _logger.warning(
                    "PCL _pcl_get_overdue_info | partner=%s | no overdue invoices",
                    commercial_partner.name,
                )
                return _EMPTY

            raw_overdue_amount = round(float(sum(inv.amount_residual for inv in overdue)), 2)
            oldest_date        = min(inv.invoice_date_due for inv in overdue)

            # Subtract session_incoming: payments made in this session to settle
            # the account are not yet reflected in amount_residual on account.move.
            effective_overdue = round(max(0.0, raw_overdue_amount - float(session_incoming)), 2)

            _logger.warning(
                "PCL _pcl_get_overdue_info | partner=%s | count=%s"
                " | raw_overdue=%.2f | session_incoming=%.2f"
                " | effective_overdue=%.2f | oldest=%s",
                commercial_partner.name,
                len(overdue),
                raw_overdue_amount,
                float(session_incoming),
                effective_overdue,
                str(oldest_date),
            )

            if effective_overdue <= 0:
                # Session payment(s) cover the full overdue balance — lift the block.
                _logger.warning(
                    "PCL _pcl_get_overdue_info | partner=%s | block LIFTED"
                    " — session payments cover overdue balance",
                    commercial_partner.name,
                )
                return _EMPTY

            return {
                'has_overdue':           True,
                'overdue_amount':        effective_overdue,
                'overdue_invoice_count': len(overdue),
                'oldest_overdue_date':   str(oldest_date),
            }

        except Exception as exc:
            # Fail-open for overdue check: a query failure must not silently
            # block the cashier. Log the error and return no-overdue so Gate 2
            # still enforces the credit limit.
            _logger.error(
                "PCL _pcl_get_overdue_info FAILED for partner %s: %s",
                commercial_partner.name, exc
            )
            return _EMPTY
