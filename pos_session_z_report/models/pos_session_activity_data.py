# -*- coding: utf-8 -*-
"""
pos_session_activity_data.py
============================
Builds the "Session Activity Summary" data for the Z-Report first sheet.

Six metrics — each as {label, left_amount, left_note, right_amount, right_note}:

  1. Standard Loyalty Points — awarded vs redeemed (loyalty_history, POS orders)
  2. Credit Note Gift Cards  — issued (–ve CNGC payments) vs redeemed (+ve CNGC payments)
  3. Customer Deposits        — received (non-credit on settlement orders) vs
                               used (credit-method on product orders, credit partners)
  4. COD Orders              — dispatched value vs collected / returned
  5. Customer Account Sales  — credit sales (credit-limit partners) vs settled
  6. Uncleared Payments      — registered vs reconciled (accounting/manual cleared)

All lookups are soft-dep guarded: missing modules / missing fields return 0 safely.
"""
import logging
from odoo import models

_logger = logging.getLogger('pos_session_z_report.activity')
_TAG = '[ZReport][Activity]'


class PosSessionZReportActivityData(models.TransientModel):
    _inherit = 'pos.session.z.report.wizard'

    # ── Public entry point ───────────────────────────────────────────────────

    def _build_activity_data(self, session):
        """Return list of metric dicts for the Session Activity Summary section.

        Each dict:
            label       str
            left_label  str   — column header for left value
            left_val    float
            left_note   str   — e.g. count or unit
            right_label str
            right_val   float
            right_note  str
        """
        _logger.info('%s _build_activity_data — session=%s id=%s',
                     _TAG, session.name, session.id)

        metrics = []
        metrics.append(self._activity_loyalty_points(session))
        metrics.append(self._activity_gift_cards(session))
        metrics.append(self._activity_deposits(session))
        metrics.append(self._activity_cod(session))
        metrics.append(self._activity_customer_account(session))
        metrics.append(self._activity_uncleared(session))

        for m in metrics:
            _logger.info(
                '%s  %-38s  left=%.2f %s  right=%.2f %s',
                _TAG, m['label'],
                m['left_val'],  m['left_note'],
                m['right_val'], m['right_note'],
            )
        return metrics

    # ── 1. Standard Loyalty Points ───────────────────────────────────────────

    def _activity_loyalty_points(self, session):
        label = 'Loyalty Points'
        zero = dict(label=label,
                    left_label='Awarded (pts)', left_val=0.0, left_note='',
                    right_label='Redeemed (pts)', right_val=0.0, right_note='')
        try:
            if 'loyalty.history' not in self.env:
                _logger.debug('%s loyalty.history model not found — skip', _TAG)
                return zero

            order_ids = session.order_ids.ids
            if not order_ids:
                return zero

            histories = self.env['loyalty.history'].sudo().search([
                ('order_id', 'in', order_ids),
                ('order_model', '=', 'pos.order'),
                ('card_id.program_id.program_type', '=', 'loyalty'),
            ])
            if 'sale.order' in self.env:
                sale_orders = self.env['sale.order'].sudo().search([
                    ('sbl_session_id', '=', session.id),
                ]) if 'sbl_session_id' in self.env['sale.order']._fields else self.env['sale.order'].browse()
                if sale_orders:
                    histories |= self.env['loyalty.history'].sudo().search([
                        ('order_id', 'in', sale_orders.ids),
                        ('order_model', '=', 'sale.order'),
                        ('card_id.program_id.program_type', '=', 'loyalty'),
                    ])
            _logger.debug(
                '%s loyalty_history records for session after loyalty-program filter: %d',
                _TAG, len(histories),
            )

            awarded  = sum(h.issued for h in histories)
            redeemed = sum(h.used   for h in histories)
            if not redeemed:
                redeemed = sum(
                    float(line.points_cost or 0.0)
                    for line in session.order_ids.mapped('lines')
                    if getattr(line, 'is_reward_line', False)
                    and getattr(line, 'points_cost', 0.0)
                    and line.coupon_id
                    and line.coupon_id.program_id.program_type == 'loyalty'
                )

            return dict(label=label,
                        left_label='Awarded (pts)', left_val=awarded,
                        left_note=f'{len(histories)} card(s)',
                        right_label='Redeemed (pts)', right_val=redeemed,
                        right_note='')
        except Exception as exc:
            _logger.error('%s _activity_loyalty_points error: %s', _TAG, exc)
            return zero

    # ── 2. Credit Note Gift Cards ─────────────────────────────────────────────

    def _activity_gift_cards(self, session):
        """
        ISSUED   = configured Credit Note Gift Card payment lines on returns.
        REDEEMED = used points on the configured gift-card loyalty program.
        """
        label = 'Credit Note Gift Cards'
        zero = dict(label=label,
                    left_label='Issued (value)', left_val=0.0, left_note='',
                    right_label='Redeemed (value)', right_val=0.0, right_note='')
        try:
            config = session.config_id
            cngc_method = (
                getattr(config, 'credit_note_payment_method_id', False)
                or self.env['pos.payment.method'].browse()
            )
            if not cngc_method or not cngc_method.exists():
                _logger.debug('%s no credit_note_payment_method_id on config — skip', _TAG)
                return zero

            issue_pmts = session.order_ids.mapped('payment_ids').filtered(
                lambda p: p.payment_method_id == cngc_method
            )
            issued = sum(abs(p.amount) for p in issue_pmts)

            redeemed = 0.0
            redeemed_count = 0
            if 'loyalty.history' in self.env:
                order_ids = session.order_ids.ids
                cngc_program = getattr(config, 'credit_note_gift_card_program_id', False)
                history_domain = [
                    ('order_id', 'in', order_ids),
                    ('order_model', '=', 'pos.order'),
                    ('used', '>', 0),
                ]
                if cngc_program:
                    history_domain.append(('card_id.program_id', '=', cngc_program.id))
                else:
                    history_domain.append(('card_id.program_id.program_type', '=', 'gift_card'))

                redeemed_histories = self.env['loyalty.history'].sudo().search(history_domain)
                redeemed = sum(h.used for h in redeemed_histories)
                redeemed_count = len(redeemed_histories)

            if not redeemed:
                cngc_program = getattr(config, 'credit_note_gift_card_program_id', False)
                redeemed_lines = session.order_ids.mapped('lines').filtered(
                    lambda line: getattr(line, 'is_reward_line', False)
                    and getattr(line, 'points_cost', 0.0)
                    and line.coupon_id
                    and (
                        (cngc_program and line.coupon_id.program_id == cngc_program)
                        or (not cngc_program and line.coupon_id.program_id.program_type == 'gift_card')
                    )
                )
                redeemed = sum(float(line.points_cost or 0.0) for line in redeemed_lines)
                redeemed_count = len(redeemed_lines)

            _logger.info(
                '%s CNGC session=%s method=%s issue_payments=%d issued=%.2f redeemed_count=%d redeemed=%.2f',
                _TAG, session.name, cngc_method.display_name,
                len(issue_pmts), issued, redeemed_count, redeemed,
            )

            return dict(label=label,
                        left_label='Issued (value)', left_val=issued,
                        left_note=f'{len(issue_pmts)} card(s)',
                        right_label='Redeemed (value)', right_val=redeemed,
                        right_note=f'{redeemed_count} use(s)')
        except Exception as exc:
            _logger.error('%s _activity_gift_cards error: %s', _TAG, exc)
            return zero

    # ── 3. Customer Account Deposits ─────────────────────────────────────────

    def _activity_deposits(self, session):
        """
        RECEIVED = non-credit payments on settlement orders (no product lines).
        USED     = credit-method positive payments on product orders.
        """
        label = 'Customer Account Deposits'
        zero = dict(label=label,
                    left_label='Received', left_val=0.0, left_note='',
                    right_label='Used in Sales', right_val=0.0, right_note='')
        try:
            all_orders = session.order_ids.filtered(
                lambda o: o.state in ('paid', 'done', 'invoiced')
            )
            settlement_orders = all_orders.filtered(lambda o: not o.lines and o.partner_id)
            product_orders    = all_orders.filtered(lambda o: o.lines)

            # RECEIVED: non-credit payments flowing INTO customer accounts
            received_pmts = settlement_orders.mapped('payment_ids').filtered(
                lambda p: not getattr(p.payment_method_id, 'pcl_is_credit_method', False)
                          and p.amount > 0
            )
            received = sum(p.amount for p in received_pmts)

            _logger.debug('%s deposits received_pmts=%d received=%.2f',
                          _TAG, len(received_pmts), received)

            # USED: credit-method positive payments on product orders
            # (customer draws from their account balance to pay for goods)
            used_pmts = product_orders.mapped('payment_ids').filtered(
                lambda p: getattr(p.payment_method_id, 'pcl_is_credit_method', False)
                          and p.amount > 0
            )
            used = sum(p.amount for p in used_pmts)
            _logger.debug('%s deposits used_pmts=%d used=%.2f', _TAG, len(used_pmts), used)

            return dict(label=label,
                        left_label='Received', left_val=received,
                        left_note=f'{len(settlement_orders)} txn(s)',
                        right_label='Used in Sales', right_val=used,
                        right_note=f'{len(used_pmts)} payment(s)')
        except Exception as exc:
            _logger.error('%s _activity_deposits error: %s', _TAG, exc)
            return zero

    # ── 4. COD Orders ────────────────────────────────────────────────────────

    def _activity_cod(self, session):
        """
        DISPATCHED = pos.order is_cod=True in this session (creation session).
        COLLECTED  = pos.cod.collection kind=payment in this session.
        RETURNED   = pos.cod.collection kind=return in this session.
        """
        label = 'COD Orders'
        zero = dict(label=label,
                    left_label='Dispatched (value)', left_val=0.0, left_note='',
                    right_label='Collected / Returned', right_val=0.0, right_note='')
        try:
            if 'pos.cod.collection' not in self.env:
                _logger.debug('%s pos.cod.collection not installed — skip', _TAG)
                return zero

            cod_orders = session.order_ids.filtered(
                lambda o: getattr(o, 'is_cod', False)
            )
            dispatched_value = sum(cod_orders.mapped('amount_total'))
            dispatched_count = len(cod_orders)

            collections = self.env['pos.cod.collection'].sudo().search([
                ('session_id', '=', session.id),
            ])
            collected = sum(c.amount for c in collections if c.kind == 'payment')
            returned  = sum(c.amount for c in collections if c.kind == 'return')

            _logger.debug(
                '%s COD dispatched=%d val=%.2f  collected=%.2f returned=%.2f',
                _TAG, dispatched_count, dispatched_value, collected, returned,
            )

            right_val  = collected
            right_note = (
                f'Collected {collected:,.2f} / Returned {returned:,.2f}'
                if returned else f'{len([c for c in collections if c.kind=="payment"])} collection(s)'
            )

            return dict(label=label,
                        left_label='Dispatched (value)', left_val=dispatched_value,
                        left_note=f'{dispatched_count} order(s)',
                        right_label='Collected / Returned', right_val=right_val,
                        right_note=right_note)
        except Exception as exc:
            _logger.error('%s _activity_cod error: %s', _TAG, exc)
            return zero

    # ── 5. Customer Account Sales vs Settled (credit-limit customers only) ───

    def _activity_customer_account(self, session):
        """
        SALES   = credit-method positive payments on product orders,
                  for partners with credit_limit > 0.
        SETTLED = non-credit payments on settlement orders (no lines),
                  for partners with credit_limit > 0.
        """
        label = 'Customer Account (credit limit)'
        zero = dict(label=label,
                    left_label='Sales (value)', left_val=0.0, left_note='',
                    right_label='Settled (value)', right_val=0.0, right_note='')
        try:
            completed = session.order_ids.filtered(
                lambda o: o.state in ('paid', 'done', 'invoiced')
            )

            def _has_credit_limit(order):
                partner = order.partner_id
                if not partner:
                    return False
                commercial = partner.commercial_partner_id
                cl = getattr(commercial, 'credit_limit', None)
                pt = getattr(commercial, 'property_payment_term_id', None)
                return bool(cl and cl > 0 and pt)

            product_orders    = completed.filtered(lambda o: o.lines)
            settlement_orders = completed.filtered(lambda o: not o.lines and o.partner_id)

            # Sales: credit method on product orders for credit-limit partners
            sales_pmts = product_orders.filtered(_has_credit_limit).mapped(
                'payment_ids'
            ).filtered(
                lambda p: getattr(p.payment_method_id, 'pcl_is_credit_method', False)
                          and p.amount > 0
            )
            sales = sum(p.amount for p in sales_pmts)

            # Settled: non-credit on settlement orders for credit-limit partners
            settled_pmts = settlement_orders.filtered(_has_credit_limit).mapped(
                'payment_ids'
            ).filtered(
                lambda p: not getattr(p.payment_method_id, 'pcl_is_credit_method', False)
                          and p.amount > 0
            )
            settled = sum(p.amount for p in settled_pmts)

            _logger.debug(
                '%s cust_account sales=%.2f settled=%.2f', _TAG, sales, settled,
            )

            return dict(label=label,
                        left_label='Sales (value)', left_val=sales,
                        left_note=f'{len(sales_pmts)} payment(s)',
                        right_label='Settled (value)', right_val=settled,
                        right_note=f'{len(settled_pmts)} payment(s)')
        except Exception as exc:
            _logger.error('%s _activity_customer_account error: %s', _TAG, exc)
            return zero

    # ── 6. Uncleared Payments ─────────────────────────────────────────────────

    def _activity_uncleared(self, session):
        """
        REGISTERED  = pos.uncleared.payment.hold where pos_session_id=session, state != cancelled.
        RECONCILED  = same filtered to state in (accounting_cleared, manual_cleared).
        """
        label = 'Uncleared Payments'
        zero = dict(label=label,
                    left_label='Registered', left_val=0.0, left_note='',
                    right_label='Reconciled', right_val=0.0, right_note='')
        try:
            if 'pos.uncleared.payment.hold' not in self.env:
                _logger.debug('%s pos.uncleared.payment.hold not installed — skip', _TAG)
                return zero

            Hold = self.env['pos.uncleared.payment.hold'].sudo()
            all_holds = Hold.search([
                ('pos_session_id', '=', session.id),
                ('state', '!=', 'cancelled'),
            ])
            reconciled = all_holds.filtered(
                lambda h: h.state in ('accounting_cleared', 'manual_cleared')
            )
            registered_total  = sum(all_holds.mapped('amount'))
            reconciled_total  = sum(reconciled.mapped('amount'))
            pending_count     = len(all_holds) - len(reconciled)

            _logger.debug(
                '%s uncleared total_holds=%d registered=%.2f reconciled=%.2f pending=%d',
                _TAG, len(all_holds), registered_total, reconciled_total, pending_count,
            )

            return dict(label=label,
                        left_label='Registered', left_val=registered_total,
                        left_note=f'{len(all_holds)} hold(s)',
                        right_label='Reconciled', right_val=reconciled_total,
                        right_note=f'{len(reconciled)} cleared / {pending_count} pending')
        except Exception as exc:
            _logger.error('%s _activity_uncleared error: %s', _TAG, exc)
            return zero
