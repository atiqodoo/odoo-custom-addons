# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger('pos_session_z_report.receipts')

_TAG = '[ZReport][Receipts]'


class PosSessionZReportReceiptsData(models.TransientModel):
    """Data-building helpers for the Receipts Detail sheet.

    Three sections:
      1. Customer Account Deposits  — settlement orders for partners whose
         current account balance is zero or negative (prepaid credit).
      2. COD Order Payments         — pos.cod.collection records for the session.
      3. Payments for Settle Due    — settlement orders for partners who still
         carry a positive outstanding balance.

    "Settlement orders" are POS orders with NO product lines and at least one
    payment via a non-credit method (cash / MPESA / bank cheque).  They are
    created by the POS "Settle Account" flow.

    Credit-method payments (pcl_is_credit_method=True, i.e. Customer Account)
    are excluded from all three sections — we only want actual money received.
    """

    _inherit = 'pos.session.z.report.wizard'

    # ── Public entry point ───────────────────────────────────────────────────

    def _build_receipts_data(self, session):
        """Return a dict consumed by _render_receipts_sheet().

        Returns:
            {
                'deposit_rows' : [{'name': str, 'amount': float, 'count': int}],
                'cod_rows'     : [{'name': str, 'amount': float, 'count': int}],
                'settle_rows'  : [{'name': str, 'amount': float, 'count': int}],
            }
        """
        _logger.info(
            '%s _build_receipts_data — session=%s id=%s',
            _TAG, session.name, session.id,
        )
        deposit_orders, settle_orders = self._split_settlement_orders(session)

        deposit_rows = self._sum_settlements_by_method(deposit_orders, 'DEPOSIT')
        cod_rows     = self._build_cod_rows(session)
        settle_rows  = self._sum_settlements_by_method(settle_orders, 'SETTLE')

        _logger.info(
            '%s result — deposit_rows=%d  cod_rows=%d  settle_rows=%d',
            _TAG, len(deposit_rows), len(cod_rows), len(settle_rows),
        )
        return {
            'deposit_rows': deposit_rows,
            'cod_rows':     cod_rows,
            'settle_rows':  settle_rows,
        }

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _split_settlement_orders(self, session):
        """Return (deposit_orders, settle_orders) from the session.

        Settlement orders: pos.order with NO product lines, a partner, and a
        completed state.  They are split by the partner's current credit balance:
          • credit <= 0  →  partner has a deposit (prepaid) balance  →  deposit
          • credit >  0  →  partner still owes money                →  settle due
        """
        all_orders = session.order_ids
        _logger.debug(
            '%s _split_settlement_orders — total orders in session: %d',
            _TAG, len(all_orders),
        )

        settlement = all_orders.filtered(
            lambda o: (
                not o.lines
                and o.partner_id
                and o.state in ('paid', 'done', 'invoiced')
            )
        )

        _logger.info(
            '%s settlement orders found: %d  (names: %s)',
            _TAG, len(settlement),
            ', '.join(settlement.mapped('name')) or 'none',
        )

        deposit_orders = settlement.filtered(
            lambda o: (o.partner_id.commercial_partner_id.credit or 0.0) <= 0
        )
        settle_orders = settlement - deposit_orders

        _logger.info(
            '%s split — deposit_orders=%d  settle_orders=%d',
            _TAG, len(deposit_orders), len(settle_orders),
        )
        for o in deposit_orders:
            _logger.debug(
                '%s  DEPOSIT  order=%s partner=%s credit=%.2f',
                _TAG, o.name, o.partner_id.name,
                o.partner_id.commercial_partner_id.credit or 0.0,
            )
        for o in settle_orders:
            _logger.debug(
                '%s  SETTLE   order=%s partner=%s credit=%.2f',
                _TAG, o.name, o.partner_id.name,
                o.partner_id.commercial_partner_id.credit or 0.0,
            )
        return deposit_orders, settle_orders

    def _sum_settlements_by_method(self, orders, label=''):
        """Aggregate non-credit payments on settlement orders by payment method.

        Args:
            orders: recordset of pos.order
            label:  log label ('DEPOSIT' or 'SETTLE')

        Returns:
            list of {'name': str, 'amount': float, 'count': int}
        """
        totals = {}
        for order in orders:
            for payment in order.payment_ids:
                method = payment.payment_method_id
                if not method:
                    _logger.debug(
                        '%s [%s] skipping payment id=%s — no method',
                        _TAG, label, payment.id,
                    )
                    continue
                # Skip Customer Account (credit) — we want physical money only
                if getattr(method, 'pcl_is_credit_method', False):
                    _logger.debug(
                        '%s [%s] skipping credit method "%s" on order %s',
                        _TAG, label, method.name, order.name,
                    )
                    continue
                _logger.debug(
                    '%s [%s] order=%s method="%s" amount=%.2f',
                    _TAG, label, order.name, method.name, payment.amount,
                )
                totals.setdefault(method, {'amount': 0.0, 'count': 0})
                totals[method]['amount'] += payment.amount
                totals[method]['count']  += 1

        rows = [
            {'name': m.name, 'amount': v['amount'], 'count': v['count']}
            for m, v in totals.items()
            if v['amount']
        ]
        _logger.info(
            '%s [%s] aggregated — %d method(s): %s',
            _TAG, label, len(rows),
            ', '.join(f"{r['name']}={r['amount']:.2f}" for r in rows) or 'none',
        )
        return rows

    def _build_cod_rows(self, session):
        """Aggregate COD collections from pos.cod.collection by payment method.

        Returns [] if pos_cod module is not installed.
        """
        if 'pos.cod.collection' not in self.env:
            _logger.info('%s pos.cod.collection model not found — skipping COD section', _TAG)
            return []

        collections = self.env['pos.cod.collection'].search([
            ('session_id', '=', session.id),
            ('kind', '=', 'payment'),
            ('amount', '>', 0),
        ])
        _logger.info(
            '%s COD collections for session %s: %d record(s)',
            _TAG, session.name, len(collections),
        )

        totals = {}
        for col in collections:
            method = col.payment_method_id
            if not method:
                _logger.debug(
                    '%s COD collection id=%s has no payment_method — skipped',
                    _TAG, col.id,
                )
                continue
            _logger.debug(
                '%s COD  method="%s" amount=%.2f', _TAG, method.name, col.amount,
            )
            totals.setdefault(method, {'amount': 0.0, 'count': 0})
            totals[method]['amount'] += col.amount
            totals[method]['count']  += 1

        rows = [
            {'name': m.name, 'amount': v['amount'], 'count': v['count']}
            for m, v in totals.items()
        ]
        _logger.info(
            '%s COD aggregated — %d method(s): %s',
            _TAG, len(rows),
            ', '.join(f"{r['name']}={r['amount']:.2f}" for r in rows) or 'none',
        )
        return rows
