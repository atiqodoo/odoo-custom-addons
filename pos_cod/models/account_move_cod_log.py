# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_COD_LOG = '[COD][MoveTransactionLog]'


class AccountMoveCodLog(models.Model):
    _inherit = 'account.move'

    cod_origin_order_id = fields.Many2one(
        'pos.order',
        string='COD Order',
        compute='_compute_cod_transaction_log',
        readonly=True,
        help='COD order whose dispatch confirmation entry is this journal entry.',
    )
    cod_collection_log_ids = fields.Many2many(
        'pos.cod.collection',
        string='COD Transaction Log',
        compute='_compute_cod_transaction_log',
        readonly=True,
        help='Read-only COD payment, return, and discount events linked to this confirmation entry.',
    )
    cod_collection_log_count = fields.Integer(
        string='COD Transaction Count',
        compute='_compute_cod_transaction_log',
        readonly=True,
    )
    cod_order_total = fields.Monetary(
        string='COD Order Total',
        currency_field='currency_id',
        compute='_compute_cod_transaction_log',
        readonly=True,
    )
    cod_open_receivable_amount = fields.Monetary(
        string='Open Receivable',
        currency_field='currency_id',
        compute='_compute_cod_transaction_log',
        readonly=True,
    )
    cod_transaction_total = fields.Monetary(
        string='All Transaction Value',
        currency_field='currency_id',
        compute='_compute_cod_transaction_log',
        readonly=True,
        help='Sum of all COD payments, returns, and discounts recorded for this order.',
    )
    cod_remaining_profit_amount = fields.Monetary(
        string='Remaining Profit',
        currency_field='currency_id',
        compute='_compute_cod_transaction_log',
        readonly=True,
    )
    cod_days_elapsed = fields.Integer(
        string='Days Elapsed',
        compute='_compute_cod_transaction_log',
        readonly=True,
        help='Whole days elapsed since the COD order was created.',
    )
    cod_order_session_id = fields.Many2one(
        'pos.session',
        string='COD Session',
        compute='_compute_cod_transaction_log',
        readonly=True,
    )
    cod_order_session_user_id = fields.Many2one(
        'res.users',
        string='Session User',
        compute='_compute_cod_transaction_log',
        readonly=True,
        help='Responsible user on the POS session that created the COD order.',
    )

    @api.depends('is_cod_entry')
    def _compute_cod_transaction_log(self):
        """Expose existing COD collection rows on the COD-CONF move only.

        This is intentionally read-only display plumbing. It does not create,
        alter, post, reconcile, or reverse any accounting, POS, or stock record.
        """
        orders_by_move = {}
        cod_moves = self.filtered(lambda move: move.is_cod_entry)
        if cod_moves:
            orders = self.env['pos.order'].search([
                ('is_cod', '=', True),
                ('cod_ar_move_id', 'in', cod_moves.ids),
            ])
            orders_by_move = {order.cod_ar_move_id.id: order for order in orders if order.cod_ar_move_id}
            _logger.debug(
                '%s compute: mapped %d COD-CONF move(s) to %d COD order(s): %s',
                _COD_LOG,
                len(cod_moves),
                len(orders),
                {
                    move_id: {
                        'order': order.name,
                        'collections': len(order.cod_collection_ids),
                    }
                    for move_id, order in orders_by_move.items()
                },
            )

        for move in self:
            order = orders_by_move.get(move.id)
            collections = order.cod_collection_ids if order else self.env['pos.cod.collection']
            transaction_total = sum(collections.mapped('amount')) if collections else 0.0
            open_receivable = order._cod_open_amount() if order else 0.0
            remaining_profit = 0.0
            if order and hasattr(order, '_cod_discount_remaining_profit_vat_incl'):
                remaining_profit = order._cod_discount_remaining_profit_vat_incl()

            days_elapsed = 0
            if order and order.date_order:
                elapsed = fields.Datetime.now() - order.date_order
                days_elapsed = max(elapsed.days, 0)

            move.cod_origin_order_id = order
            move.cod_collection_log_ids = collections
            move.cod_collection_log_count = len(collections)
            move.cod_order_total = order.amount_total if order else 0.0
            move.cod_open_receivable_amount = open_receivable
            move.cod_transaction_total = transaction_total
            move.cod_remaining_profit_amount = remaining_profit
            move.cod_days_elapsed = days_elapsed
            move.cod_order_session_id = order.session_id if order else False
            move.cod_order_session_user_id = order.session_id.user_id if order and order.session_id else False

            if order:
                _logger.debug(
                    '%s source summary: move=%s order=%s total=%.2f open=%.2f '
                    'transactions=%.2f remaining_profit=%.2f days_elapsed=%s '
                    'session=%s session_user=%s',
                    _COD_LOG,
                    move.name,
                    order.name,
                    move.cod_order_total,
                    move.cod_open_receivable_amount,
                    move.cod_transaction_total,
                    move.cod_remaining_profit_amount,
                    move.cod_days_elapsed,
                    order.session_id.name,
                    order.session_id.user_id.name,
                )

            if move.is_cod_entry and not order:
                _logger.warning(
                    '%s compute: COD entry %s (%s) has no pos.order.cod_ar_move_id link.',
                    _COD_LOG,
                    move.id,
                    move.name,
                )
