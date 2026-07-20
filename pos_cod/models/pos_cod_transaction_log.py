# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_COD_LOG = '[COD][TransactionLog]'


class PosCodCollectionTransactionLog(models.Model):
    _inherit = 'pos.cod.collection'

    cod_source_order_id = fields.Many2one(
        'pos.order',
        string='COD Order',
        related='order_id',
        store=True,
        readonly=True,
    )
    cod_source_order_date = fields.Datetime(
        string='COD Order Date',
        related='order_id.date_order',
        store=True,
        readonly=True,
    )
    cod_source_order_session_id = fields.Many2one(
        'pos.session',
        string='COD Session',
        related='order_id.session_id',
        store=True,
        readonly=True,
    )
    cod_source_order_session_user_id = fields.Many2one(
        'res.users',
        string='COD Session User',
        related='order_id.session_id.user_id',
        store=True,
        readonly=True,
    )
    cod_source_customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='order_id.partner_id',
        store=True,
        readonly=True,
    )
    cod_source_delivery_employee_id = fields.Many2one(
        'hr.employee',
        string='Delivery Employee',
        related='order_id.delivery_employee_id',
        store=True,
        readonly=True,
    )
    cod_source_state = fields.Selection(
        related='order_id.cod_state',
        string='COD State',
        store=True,
        readonly=True,
    )
    cod_source_order_total = fields.Monetary(
        string='COD Order Total',
        related='order_id.amount_total',
        currency_field='currency_id',
        store=True,
        readonly=True,
    )
    cod_source_open_receivable_amount = fields.Monetary(
        string='Open Receivable',
        currency_field='currency_id',
        compute='_compute_cod_source_amounts',
        store=True,
        readonly=True,
    )
    cod_source_transaction_total = fields.Monetary(
        string='All Transaction Value',
        currency_field='currency_id',
        compute='_compute_cod_source_amounts',
        store=True,
        readonly=True,
        help='Sum of all COD payments, returns, and discounts recorded for this COD order.',
    )
    cod_source_remaining_profit_amount = fields.Monetary(
        string='Remaining Profit',
        currency_field='currency_id',
        compute='_compute_cod_source_amounts',
        store=True,
        readonly=True,
    )
    cod_source_days_elapsed = fields.Integer(
        string='Days Elapsed',
        compute='_compute_cod_source_amounts',
        store=True,
        readonly=True,
        help='Whole days elapsed since the COD order was created.',
    )

    @api.depends(
        'order_id',
        'order_id.amount_total',
        'order_id.date_order',
        'order_id.cod_collection_ids.amount',
        'order_id.cod_collection_ids.kind',
        'order_id.cod_collection_ids.return_line_qtys',
    )
    def _compute_cod_source_amounts(self):
        for collection in self:
            order = collection.order_id
            if not order:
                collection.cod_source_open_receivable_amount = 0.0
                collection.cod_source_transaction_total = 0.0
                collection.cod_source_remaining_profit_amount = 0.0
                collection.cod_source_days_elapsed = 0
                continue

            collections = order.cod_collection_ids
            collection.cod_source_open_receivable_amount = order._cod_open_amount()
            collection.cod_source_transaction_total = sum(collections.mapped('amount'))
            collection.cod_source_remaining_profit_amount = (
                order._cod_discount_remaining_profit_vat_incl()
                if hasattr(order, '_cod_discount_remaining_profit_vat_incl')
                else 0.0
            )
            collection.cod_source_days_elapsed = max(
                (fields.Datetime.now() - order.date_order).days,
                0,
            ) if order.date_order else 0

            _logger.debug(
                '%s source: collection=%s order=%s total=%.2f open=%.2f '
                'transactions=%.2f remaining_profit=%.2f days_elapsed=%s',
                _COD_LOG,
                collection.id,
                order.name,
                collection.cod_source_order_total,
                collection.cod_source_open_receivable_amount,
                collection.cod_source_transaction_total,
                collection.cod_source_remaining_profit_amount,
                collection.cod_source_days_elapsed,
            )
