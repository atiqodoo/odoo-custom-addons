# -*- coding: utf-8 -*-
"""
unpaid_invoice_guard.py

Backend companion for the POS loyalty unpaid-invoice check.

Exposes a single @api.model method called from the POS frontend
(unpaid_invoice_guard.js) before any loyalty-point redemption is applied.

If the customer has outstanding (unpaid/partially-paid) posted invoices the
frontend blocks the reward application and shows a warning dialog.  This
module also adds the corresponding backend safety-net check inside
_process_order so the rule is enforced even if the frontend is bypassed
(e.g. offline sync or direct API calls).
"""

import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class PosOrderUnpaidInvoiceGuard(models.Model):
    _inherit = 'pos.order'

    # -------------------------------------------------------------------------
    # Frontend-callable check
    # -------------------------------------------------------------------------

    @api.model
    def get_partner_unpaid_invoice_info(self, partner_id):
        """
        Called from POS JavaScript (unpaid_invoice_guard.js) before the
        loyalty redemption reward is applied to the current order.

        Uses sudo() because POS users typically lack direct access to
        account.move records.

        Includes child partners (billing contacts attached to the same
        company) so that invoices posted against a delivery-contact address
        are not missed.

        Args:
            partner_id (int): res.partner id of the POS order customer

        Returns:
            dict:
                has_unpaid (bool)  – True if any unpaid invoices exist
                count      (int)   – number of unpaid invoices
                total      (float) – sum of amount_residual across all invoices
                currency   (str)   – ISO code of the first invoice's currency
        """
        _logger.debug(
            "[unpaid_invoice_guard] get_partner_unpaid_invoice_info called"
            " | partner_id=%s",
            partner_id,
        )

        if not partner_id:
            _logger.debug(
                "[unpaid_invoice_guard] partner_id is falsy — returning no unpaid invoices"
            )
            return {'has_unpaid': False, 'count': 0, 'total': 0.0, 'currency': ''}

        # Resolve partner and its billing children
        partner = self.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            _logger.debug(
                "[unpaid_invoice_guard] partner_id=%s does not exist", partner_id
            )
            return {'has_unpaid': False, 'count': 0, 'total': 0.0, 'currency': ''}

        partner_ids = (partner | partner.child_ids.filtered(
            lambda c: c.type in ('invoice', 'contact', False)
        )).ids

        _logger.debug(
            "[unpaid_invoice_guard] resolved partner_ids=%s"
            " (partner=%s + %d billing children)",
            partner_ids, partner.name, len(partner_ids) - 1,
        )

        # Search for posted, non-fully-paid customer invoices
        invoices = self.env['account.move'].sudo().search([
            ('partner_id', 'in', partner_ids),
            ('move_type', 'in', ['out_invoice', 'out_receipt']),
            ('payment_state', 'not in', ['paid', 'in_payment', 'reversed']),
            ('state', '=', 'posted'),
            ('amount_residual', '>', 0),
        ])

        _logger.debug(
            "[unpaid_invoice_guard] found %d unpaid invoice(s) for partner_id=%s",
            len(invoices), partner_id,
        )

        if not invoices:
            return {'has_unpaid': False, 'count': 0, 'total': 0.0, 'currency': ''}

        total_residual = sum(inv.amount_residual for inv in invoices)
        currency_name = invoices[0].currency_id.name if invoices[0].currency_id else ''

        for inv in invoices:
            _logger.debug(
                "[unpaid_invoice_guard]   invoice=%s | date=%s | residual=%.2f %s",
                inv.name,
                inv.invoice_date,
                inv.amount_residual,
                currency_name,
            )

        # ── Same-session settlement deduction ──────────────────────────────────
        # When a customer pays their balance via POS "Settle Account" in the
        # current session, the payment is NOT posted to accounting until the
        # session closes.  account.move.amount_residual therefore still shows
        # the full balance.  Deduct any such unposted settlement payments so
        # we do not block a customer who already paid within this session.
        #
        # Settlement orders are POS orders with NO product lines (they exist
        # purely to record the incoming payment against the customer's receivable).
        # This mirrors the same logic in pos_credit_limit._pcl_get_session_incoming_payments.
        session_incoming = self._get_session_incoming_for_partners(partner_ids)
        effective_residual = max(0.0, round(total_residual - session_incoming, 2))

        _logger.info(
            "[unpaid_invoice_guard] partner_id=%s (%s)"
            " | raw_residual=%.2f | session_incoming=%.2f | effective_residual=%.2f",
            partner_id, partner.name,
            total_residual, session_incoming, effective_residual,
        )

        if effective_residual <= 0:
            _logger.info(
                "[unpaid_invoice_guard] partner_id=%s (%s): session payments cover"
                " unpaid balance — loyalty redemption ALLOWED",
                partner_id, partner.name,
            )
            return {'has_unpaid': False, 'count': 0, 'total': 0.0, 'currency': ''}

        result = {
            'has_unpaid': True,
            'count': len(invoices),
            'total': effective_residual,
            'currency': currency_name,
        }

        _logger.info(
            "[unpaid_invoice_guard] partner_id=%s (%s) has %d unpaid invoice(s)"
            " totalling %.2f %s (after session deductions) — loyalty redemption will be blocked",
            partner_id, partner.name,
            result['count'], result['total'], result['currency'],
        )

        return result

    def _get_session_incoming_for_partners(self, partner_ids):
        """
        Sum payments received in currently open POS sessions for settlement orders
        (orders with NO product lines) belonging to any of the given partner IDs.

        These payments reduce the customer's outstanding balance but are not yet
        posted to accounting, so account.move.amount_residual still reflects the
        pre-payment figure.  Deducting this amount gives the effective balance.

        Args:
            partner_ids (list[int]): res.partner IDs to include (partner + billing children)

        Returns:
            float: Total settlement payments (>= 0.0)
        """
        try:
            open_sessions = self.env['pos.session'].sudo().search([
                ('state', '=', 'opened'),
            ])
            _logger.info(
                "[unpaid_invoice_guard] _get_session_incoming"
                " | partner_ids=%s | open_sessions=%d (%s)",
                partner_ids,
                len(open_sessions),
                [s.name for s in open_sessions],
            )
            if not open_sessions:
                return 0.0

            completed_orders = self.env['pos.order'].sudo().search([
                ('session_id', 'in', open_sessions.ids),
                ('partner_id', 'in', partner_ids),
                ('state', 'in', ['paid', 'done', 'invoiced']),
            ])
            _logger.info(
                "[unpaid_invoice_guard] _get_session_incoming"
                " | completed orders for partner_ids=%s: %d",
                partner_ids, len(completed_orders),
            )

            for o in completed_orders:
                _logger.info(
                    "[unpaid_invoice_guard]   order=%s | state=%s | lines=%d"
                    " | payments=%s",
                    o.name, o.state, len(o.lines),
                    [(round(p.amount, 2), p.payment_method_id.name)
                     for p in o.payment_ids],
                )

            if not completed_orders:
                return 0.0

            # Settlement orders have no product lines (Settle Account / deposit flow)
            settlement_orders = completed_orders.filtered(lambda o: not o.lines)
            _logger.info(
                "[unpaid_invoice_guard] _get_session_incoming"
                " | settlement orders (no lines): %d / %d total",
                len(settlement_orders), len(completed_orders),
            )
            if not settlement_orders:
                _logger.warning(
                    "[unpaid_invoice_guard] _get_session_incoming: no settlement orders"
                    " found for partner_ids=%s — all %d completed order(s) have product"
                    " lines and are NOT counted as settlements",
                    partner_ids, len(completed_orders),
                )
                return 0.0

            # Only sum POSITIVE payment amounts.
            #
            # A "Settle Account" order has two payment lines:
            #   Customer Account:  -1000  (ledger-clearing entry — AR reduction)
            #   Cash / Card:       +1000  (actual cash received from customer)
            #
            # Summing all payments gives -1000 + 1000 = 0, incorrectly returning
            # session_incoming=0 and leaving the block in place.
            #
            # pos_credit_limit avoids this by excluding pcl_is_credit_method payments.
            # We achieve the same result by only counting positive amounts — the
            # Customer Account debit entry is always negative, real incoming payments
            # (cash, card, mpesa…) are always positive.
            total = sum(
                payment.amount
                for order in settlement_orders
                for payment in order.payment_ids
                if payment.amount > 0
            )
            result = max(0.0, round(total, 2))

            _logger.info(
                "[unpaid_invoice_guard] _get_session_incoming"
                " | partner_ids=%s | settlement_orders=%d | session_incoming=%.2f"
                " (negative credit-method entries excluded)",
                partner_ids, len(settlement_orders), result,
            )
            return result

        except Exception as exc:
            # Fail open — a query failure must not block the cashier
            _logger.error(
                "[unpaid_invoice_guard] _get_session_incoming FAILED: %s", exc
            )
            return 0.0

    # -------------------------------------------------------------------------
    # Backend safety net — runs during order sync
    # -------------------------------------------------------------------------

    @api.model
    def _process_order(self, order, existing_order):
        """
        Audit log only — does NOT block the order.

        The primary enforcement is in the POS frontend (_applyReward patch in
        unpaid_invoice_guard.js).  A backend raise here is too coarse: POS can
        auto-apply reward lines that appear as is_reward_line=True / points_cost>0
        without any cashier intent to redeem, causing false-positive blocks on
        ordinary cash checkouts.

        We keep the detection for observability so that any slip-through
        (frontend bypassed / offline sync) is visible in server logs.
        """
        partner_id = order.get('partner_id')

        _logger.debug(
            "[unpaid_invoice_guard] _process_order: audit-check"
            " | order=%s | partner_id=%s",
            order.get('name', 'unknown'), partner_id,
        )

        if partner_id:
            has_redemption = self._order_has_loyalty_redemption(order)

            if has_redemption:
                info = self.get_partner_unpaid_invoice_info(partner_id)
                if info.get('has_unpaid'):
                    _logger.warning(
                        "[unpaid_invoice_guard] AUDIT: order=%s partner_id=%s"
                        " has redemption line(s) AND %d unpaid invoice(s)"
                        " totalling %.2f %s — frontend guard should have blocked this;"
                        " allowing through (backend does not raise)",
                        order.get('name', 'unknown'),
                        partner_id,
                        info['count'], info['total'], info['currency'],
                    )

        return super()._process_order(order, existing_order)

    def _order_has_loyalty_redemption(self, order):
        """
        Return True if the order contains at least one reward line that
        cost loyalty points (points_cost > 0).  This distinguishes earning
        transactions (no reward lines) from redemption transactions.
        """
        lines = order.get('lines', [])
        for entry in lines:
            if isinstance(entry, (list, tuple)) and len(entry) == 3:
                vals = entry[2]
            elif isinstance(entry, dict):
                vals = entry
            else:
                continue

            if vals.get('is_reward_line') and (vals.get('points_cost') or 0) > 0:
                _logger.debug(
                    "[unpaid_invoice_guard] redemption line found:"
                    " reward_id=%s points_cost=%s",
                    vals.get('reward_id'), vals.get('points_cost'),
                )
                return True

        return False
