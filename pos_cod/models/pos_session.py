# -*- coding: utf-8 -*-
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

_COD = '[COD][PosSession]'


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _cod_collection_orders(self):
        return self.env['pos.order'].search([
            ('is_cod', '=', True),
            ('cod_state', '=', 'paid'),
            ('cod_collection_session_id', 'in', self.ids),
            ('cod_collection_amount', '>', 0),
        ])

    def _cod_collection_totals_by_method(self):
        totals = {}
        collections = self.env['pos.cod.collection'].search([
            ('session_id', 'in', self.ids),
            ('kind', '=', 'payment'),
            ('amount', '>', 0),
        ])
        for collection in collections:
            payment_method = collection.payment_method_id
            if not payment_method:
                continue
            totals.setdefault(payment_method, {'amount': 0.0, 'number': 0})
            totals[payment_method]['amount'] += collection.amount
            totals[payment_method]['number'] += 1
        return totals

    def _cod_cash_collection_total(self):
        total = 0.0
        for payment_method, values in self._cod_collection_totals_by_method().items():
            if payment_method.is_cash_count:
                total += values['amount']
        return total

    @api.depends('payment_method_ids', 'order_ids', 'cash_register_balance_start')
    def _compute_cash_balance(self):
        """Include cash COD collections in expected cash for blind audit.

        COD collections post their own DR Cash/Bank / CR COD AR entry, so they
        are not stored as normal pos.payment rows.  This makes the expected
        physical cash match what the cashier actually received in this session.
        """
        super()._compute_cash_balance()
        for session in self:
            cod_cash_total = session._cod_cash_collection_total()
            if cod_cash_total:
                session.cash_register_balance_end += cod_cash_total
                session.cash_register_difference = (
                    session.cash_register_balance_end_real
                    - session.cash_register_balance_end
                )

    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        self.ensure_one()

        for payment_method, values in self._cod_collection_totals_by_method().items():
            amount = values['amount']
            if not amount:
                continue

            default_cash_id = data.get('default_cash_details', {}).get('id')
            if default_cash_id and payment_method.id == default_cash_id:
                data['default_cash_details']['amount'] += amount
                data['default_cash_details']['payment_amount'] += amount
                continue

            for method_data in data.get('non_cash_payment_methods', []):
                if method_data.get('id') == payment_method.id:
                    method_data['amount'] += amount
                    method_data['number'] += values['number']
                    break

        return data

    def _cod_filter_close_orders(self, orders):
        """Exclude COD orders from standard POS close validation/accounting."""
        return orders.filtered(lambda o: not o.is_cod)

    def get_session_orders(self):
        orders = super().get_session_orders()
        if self.env.context.get('cod_skip_orders'):
            return self._cod_filter_close_orders(orders)
        return orders

    def action_pos_session_closing_control(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """Warn (but do not block) if pending COD orders exist when closing the session.

        COD orders in draft/pending state are intentionally left open — they survive
        session close and remain accessible from the COD Orders screen in future sessions.
        They are NOT included in session accounting (state != paid) so closing is safe.
        """
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True).action_pos_session_closing_control(
                balancing_account=balancing_account,
                amount_to_balance=amount_to_balance,
                bank_payment_method_diffs=bank_payment_method_diffs,
            )

        pending = self.env['pos.order'].search([
            ('session_id', 'in', self.ids),
            ('is_cod', '=', True),
            ('cod_state', '=', 'pending'),
        ])

        if pending:
            names = ', '.join(pending.mapped('name'))
            _logger.warning(
                '%s action_pos_session_closing_control: session "%s" has %d pending COD order(s): %s. '
                'These orders will remain accessible in the COD Orders screen after session close.',
                _COD, self.name, len(pending), names,
            )
        else:
            _logger.info(
                '%s action_pos_session_closing_control: session "%s" — no pending COD orders.',
                _COD, self.name,
            )

        return super().action_pos_session_closing_control(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs,
        )

    def close_session_from_ui(self, bank_payment_method_diff_pairs=None):
        """Run normal close chain with COD orders hidden from core draft checks.

        This composes with pos_blind_audit: its variance gate still runs, then
        Odoo core sees a close-only order list without pending COD orders.
        """
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True).close_session_from_ui(
                bank_payment_method_diff_pairs=bank_payment_method_diff_pairs,
            )
        return super().close_session_from_ui(bank_payment_method_diff_pairs)

    def _cannot_close_session(self, bank_payment_method_diffs=None):
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True)._cannot_close_session(
                bank_payment_method_diffs=bank_payment_method_diffs,
            )
        return super()._cannot_close_session(bank_payment_method_diffs)

    def _check_if_no_draft_orders(self):
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True)._check_if_no_draft_orders()
        return super()._check_if_no_draft_orders()

    def _get_closed_orders(self):
        orders = super()._get_closed_orders()
        if self.env.context.get('cod_skip_orders'):
            orders = self._cod_filter_close_orders(orders)
        return orders

    def _accumulate_amounts(self, data):
        """Exclude COD orders from session-close accounting accumulation.

        COD dispatch entries (DR COD AR / CR Sales) are posted directly at dispatch.
        COD collection entries (DR Cash / CR COD AR) are posted directly in
        collect_cod_payment(). The pos.payment records created there are purely for
        session closing-report display; re-processing them here would double-count.

        Guard: if the context flag is already set we are in the filtered re-entry,
        so call super() directly to avoid infinite recursion.
        """
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True)._accumulate_amounts(data)
        return super()._accumulate_amounts(data)

    def _create_picking_at_end_of_session(self):
        """Skip COD orders from session-close picking creation.

        COD order pickings are created and immediately validated at dispatch time
        by _cod_validate_picking(). Including them here would generate duplicate
        stock moves.

        Guard: same pattern as _accumulate_amounts to avoid recursion.
        """
        if not self.env.context.get('cod_skip_orders'):
            return self.with_context(cod_skip_orders=True)._create_picking_at_end_of_session()
        return super()._create_picking_at_end_of_session()
