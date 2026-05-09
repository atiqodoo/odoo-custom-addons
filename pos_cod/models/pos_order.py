# -*- coding: utf-8 -*-
import logging
from uuid import uuid4
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

_COD = '[COD][PosOrder]'


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # ── COD fields ────────────────────────────────────────────────────────────

    is_cod = fields.Boolean(
        string='Cash on Delivery',
        default=False,
        index=True,
        help='Order dispatched as COD: stock moved immediately, payment collected later.',
    )
    cod_state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('out_for_delivery', 'Out for Delivery'),
            ('delivered', 'Delivered'),
            ('partial', 'Partially Paid'),
            ('returned', 'Returned'),
            ('paid', 'Paid'),
        ],
        string='COD State',
        default='pending',
        index=True,
    )
    delivery_employee_id = fields.Many2one(
        'hr.employee',
        string='Delivery Employee',
        ondelete='set null',
    )
    delivery_address = fields.Char(string='Delivery Address')
    delivery_notes = fields.Text(string='Delivery Notes')
    cod_ar_move_id = fields.Many2one(
        'account.move',
        string='COD AR Journal Entry',
        ondelete='set null',
        readonly=True,
        copy=False,
        help='The confirmation journal entry (DR COD AR / CR Sales) created at dispatch.',
    )
    cod_payment_move_id = fields.Many2one(
        'account.move',
        string='COD Payment Journal Entry',
        ondelete='set null',
        readonly=True,
        copy=False,
        help='The collection journal entry (DR Cash/Bank / CR COD AR) created when COD is paid.',
    )
    cod_collection_session_id = fields.Many2one(
        'pos.session',
        string='COD Collection Session',
        ondelete='set null',
        readonly=True,
        copy=False,
        index=True,
        help='The POS session/terminal that collected this COD payment.',
    )
    cod_collection_payment_method_id = fields.Many2one(
        'pos.payment.method',
        string='COD Collection Payment Method',
        ondelete='set null',
        readonly=True,
        copy=False,
        help='The current terminal payment method used to collect this COD payment.',
    )
    cod_collection_amount = fields.Monetary(
        string='COD Collected Amount',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Amount collected by the collection session for closing control totals.',
    )
    cod_collection_ids = fields.One2many('pos.cod.collection', 'order_id', string='COD Collections')
    cod_amount_paid = fields.Monetary(
        string='COD Paid',
        currency_field='currency_id',
        compute='_compute_cod_amounts',
    )
    cod_amount_returned = fields.Monetary(
        string='COD Returned',
        currency_field='currency_id',
        compute='_compute_cod_amounts',
    )
    cod_amount_open = fields.Monetary(
        string='COD Open Balance',
        currency_field='currency_id',
        compute='_compute_cod_amounts',
    )

    @api.depends('amount_total', 'cod_collection_ids.amount', 'cod_collection_ids.kind')
    def _compute_cod_amounts(self):
        for order in self:
            paid = sum(order.cod_collection_ids.filtered(lambda c: c.kind == 'payment').mapped('amount'))
            returned = sum(order.cod_collection_ids.filtered(lambda c: c.kind == 'return').mapped('amount'))
            order.cod_amount_paid = paid
            order.cod_amount_returned = returned
            order.cod_amount_open = max(round(order.amount_total - paid - returned, 2), 0.0)

    def _cod_fresh_payload(self, order, existing_order=False):
        """Return a new-order COD payload when the frontend reuses stale IDs.

        POS may resend an old UUID/local id after a browser reload or after a
        previous order was removed from the screen.  Core sync_from_ui ignores
        such payloads when the matching order is already paid, so COD dispatch
        would look successful but no new COD order would be created.
        """
        order_copy = dict(order)
        original_uuid = order_copy.get('uuid')

        order_copy.pop('id', None)
        order_copy['uuid'] = str(uuid4())
        order_copy['access_token'] = str(uuid4())
        order_copy['state'] = 'draft'
        order_copy['payment_ids'] = []
        order_copy['amount_paid'] = 0
        order_copy['amount_return'] = -abs(float(order_copy.get('amount_total') or 0.0))

        fresh_lines = []
        for command in order_copy.get('lines') or []:
            if len(command) < 3 or not isinstance(command[2], dict):
                fresh_lines.append(command)
                continue

            line_vals = dict(command[2])
            line_vals.pop('id', None)
            line_vals.pop('order_id', None)
            line_vals['uuid'] = str(uuid4())

            fresh_lots = []
            for lot_command in line_vals.get('pack_lot_ids') or []:
                if len(lot_command) >= 3 and isinstance(lot_command[2], dict):
                    lot_vals = dict(lot_command[2])
                    lot_vals.pop('id', None)
                    lot_vals.pop('pos_order_line_id', None)
                    fresh_lots.append([0, 0, lot_vals])
                else:
                    fresh_lots.append(lot_command)
            line_vals['pack_lot_ids'] = fresh_lots

            # Combo links use frontend-local ids; after cloning they are no
            # longer reliable.  Keeping the sellable lines is safer than
            # letting stale combo ids block COD dispatch.
            line_vals['combo_parent_id'] = False
            line_vals['combo_line_ids'] = []
            fresh_lines.append([0, 0, line_vals])
        order_copy['lines'] = fresh_lines

        _logger.warning(
            '%s _cod_fresh_payload: cloned COD payload name=%s old_uuid=%s new_uuid=%s '
            'existing_order=%s state=%s',
            _COD,
            order.get('name'),
            original_uuid,
            order_copy.get('uuid'),
            existing_order.id if existing_order else False,
            existing_order.state if existing_order else False,
        )
        return order_copy

    # ── sync_from_ui override ─────────────────────────────────────────────────

    @api.model
    def sync_from_ui(self, orders):
        """Intercept new COD dispatch orders for separate processing.

        Splits incoming orders into:
          cod_new — new COD orders (no server id): dispatch flow
          normal  — all other orders: standard POS flow

        COD payment collection uses the collect_cod_payment() RPC directly
        from CodOrdersScreen and never passes through here.
        """
        cod_new = []
        normal = []

        for order in orders:
            is_cod = order.get('is_cod', False)
            existing_order = self._get_open_order(order) if is_cod else False

            if is_cod:
                # Force draft so _process_order skips action_pos_order_paid.
                if (
                    existing_order
                    and existing_order.is_cod
                    and existing_order.cod_ar_move_id
                    and round(existing_order.amount_total, 2) == round(float(order.get('amount_total') or 0.0), 2)
                    and existing_order.partner_id.id == order.get('partner_id')
                ):
                    _logger.info(
                        '%s sync_from_ui: duplicate COD retry ignored safely name=%s existing_id=%s',
                        _COD, order.get('name'), existing_order.id,
                    )
                    r = existing_order.read_pos_data([order], existing_order.config_id.id)
                    for k, v in r.items():
                        merged.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                    continue

                if existing_order and not (
                    existing_order.state == 'draft' and not existing_order.cod_ar_move_id
                ):
                    order_copy = self._cod_fresh_payload(order, existing_order)
                else:
                    order_copy = dict(order)
                    order_copy['state'] = 'draft'
                cod_new.append(order_copy)
            else:
                normal.append(order)

        merged = {}

        if normal:
            r = super().sync_from_ui(normal)
            for k, v in r.items():
                merged.setdefault(k, []).extend(v if isinstance(v, list) else [v])

        for order_data in cod_new:
            if not order_data.get('partner_id'):
                raise ValidationError(
                    'COD order "%s" has no customer. '
                    'A customer is required for COD accounting (receivable tracking).'
                    % order_data.get('name', '')
                )

            _logger.info(
                '%s sync_from_ui: new COD order name=%s partner_id=%s lines=%s',
                _COD, order_data.get('name', '?'), order_data.get('partner_id'),
                len(order_data.get('lines', [])),
            )

            r = super().sync_from_ui([order_data])

            pos_orders = r.get('pos.order', [])
            if not pos_orders:
                raise UserError(
                    'COD: sync_from_ui returned no order for "%s".' % order_data.get('name', '')
                )

            order_id = pos_orders[0].get('id') if isinstance(pos_orders[0], dict) else pos_orders[0]
            order = self.browse(int(order_id))

            if not order.exists():
                raise UserError('COD: order record id=%s not found after creation.' % order_id)

            _logger.info('%s sync_from_ui: record created id=%s name=%s', _COD, order.id, order.name)
            order._cod_validate_picking()
            order._cod_post_ar_entry()
            # Move out of draft so session close is not blocked.
            # cod_state='pending' tracks the outstanding delivery; state='paid'
            # tells POS the order is finalised from the session's perspective.
            order.write({'state': 'paid'})

            for k, v in r.items():
                merged.setdefault(k, []).extend(v if isinstance(v, list) else [v])

        return merged or {'pos.order': []}

    # ── action_pos_order_paid override ────────────────────────────────────────

    def action_pos_order_paid(self):
        """Intercept payment processing for pending COD orders.

        For a COD order in cod_state='pending':
          - Skip standard POS journal entry (already done via _cod_post_ar_entry)
          - Skip duplicate picking creation (already done at dispatch)
          - Post DR Cash / CR COD AR entry and reconcile
          - Set cod_state='paid', state='paid'

        All other orders use the standard flow.
        """
        if self.is_cod and self.cod_state == 'pending' and self.payment_ids:
            _logger.info(
                '%s action_pos_order_paid: COD collection via payment screen for order %s (amount_total=%.2f)',
                _COD, self.name, self.amount_total,
            )
            return self._cod_collect_payment()
        return super().action_pos_order_paid()

    def _cod_collect_payment(self):
        """Process payment accounting for a COD order being collected.

        Validates payment amount, creates the DR Cash / CR COD AR entry,
        reconciles it against the confirmation entry, and marks the order paid.
        """
        self.ensure_one()

        if not self.partner_id:
            raise UserError('COD payment requires a customer on order %s.' % self.name)

        if not self.payment_ids:
            raise UserError('No payment lines found on COD order %s.' % self.name)

        total_paid = round(sum(p.amount for p in self.payment_ids), 2)
        order_total = round(self.amount_total, 2)

        _logger.info(
            '%s _cod_collect_payment: order=%s total_paid=%.2f order_total=%.2f',
            _COD, self.name, total_paid, order_total,
        )

        if abs(total_paid - order_total) > 0.01:
            raise UserError(
                'COD payment amount (%.2f) does not match order total (%.2f) for order %s. '
                'Verify the payment before proceeding.' % (total_paid, order_total, self.name)
            )

        payment_entry = self._cod_create_payment_entry()
        self._cod_reconcile(payment_entry)

        self.write({'cod_state': 'paid', 'state': 'paid'})

        _logger.info(
            '%s _cod_collect_payment: order %s marked paid. Entry: %s.',
            _COD, self.name, payment_entry.name,
        )
        return True

    # ── RPC endpoint for COD Orders Screen ───────────────────────────────────

    def _cod_paid_total(self):
        self.ensure_one()
        return sum(self.cod_collection_ids.filtered(lambda c: c.kind == 'payment').mapped('amount'))

    def _cod_return_total(self):
        self.ensure_one()
        return sum(self.cod_collection_ids.filtered(lambda c: c.kind == 'return').mapped('amount'))

    def _cod_open_amount(self):
        self.ensure_one()
        return max(round(self.amount_total - self._cod_paid_total() - self._cod_return_total(), 2), 0.0)

    def _cod_normalize_return_lines(self, return_lines=None):
        qty_map = {}
        for item in return_lines or []:
            product_id = int(item.get('product_id') or 0)
            qty = round(float(item.get('qty') or 0.0), 4)
            if product_id and qty > 0:
                qty_map[product_id] = round(qty_map.get(product_id, 0.0) + qty, 4)
        return [{'product_id': product_id, 'qty': qty} for product_id, qty in qty_map.items() if qty > 0]

    def _cod_returned_qty_by_product(self):
        self.ensure_one()
        returned = {}
        for collection in self.cod_collection_ids.filtered(lambda c: c.kind == 'return'):
            for item in collection.return_line_qtys or []:
                product_id = int(item.get('product_id') or 0)
                qty = float(item.get('qty') or 0.0)
                if product_id and qty > 0:
                    returned[product_id] = round(returned.get(product_id, 0.0) + qty, 4)
        return returned

    def _cod_remaining_qty_by_product(self):
        self.ensure_one()
        ordered = {}
        for line in self.lines.filtered(lambda l: l.qty > 0):
            ordered[line.product_id.id] = round(ordered.get(line.product_id.id, 0.0) + float(line.qty), 4)

        returned = self._cod_returned_qty_by_product()
        return {
            product_id: max(round(qty - returned.get(product_id, 0.0), 4), 0.0)
            for product_id, qty in ordered.items()
        }

    @api.model
    def get_cod_return_lines(self, order_id=None, order_ref=None):
        order = self.browse(int(order_id)) if order_id else self.browse()
        if order_ref and (not order.exists() or not order.is_cod):
            order = self.search([
                ('is_cod', '=', True),
                ('cod_state', 'in', ('pending', 'partial')),
                '|',
                ('name', '=', order_ref),
                ('pos_reference', '=', order_ref),
            ], limit=1)

        if not order.exists() or not order.is_cod:
            return []

        returned_by_product = order._cod_returned_qty_by_product()
        rows = []
        for line in order.lines.filtered(lambda l: l.qty > 0).sorted(lambda l: l.id):
            product_id = line.product_id.id
            already_returned = min(float(line.qty), returned_by_product.get(product_id, 0.0))
            returned_by_product[product_id] = max(round(returned_by_product.get(product_id, 0.0) - already_returned, 4), 0.0)
            remaining_qty = max(round(float(line.qty) - already_returned, 4), 0.0)
            if remaining_qty <= 0:
                continue
            rows.append({
                'id': line.id,
                'product_id': [product_id, line.product_id.display_name],
                'full_product_name': line.full_product_name or line.product_id.display_name,
                'qty': float(line.qty),
                'returned_qty': already_returned,
                'remaining_qty': remaining_qty,
                'price_unit': float(line.price_unit),
                'price_subtotal_incl': float(line.price_subtotal_incl),
                'discount': float(line.discount or 0.0),
            })
        return rows

    @api.model
    def get_cod_order_lines(self, order_id=None, order_ref=None):
        """Read-only COD line details for the POS card item viewer."""
        order = self.browse(int(order_id)) if order_id else self.browse()
        if order_ref and (not order.exists() or not order.is_cod):
            order = self.search([
                ('is_cod', '=', True),
                ('cod_state', 'in', ('pending', 'partial')),
                '|',
                ('name', '=', order_ref),
                ('pos_reference', '=', order_ref),
            ], limit=1)

        if not order.exists() or not order.is_cod:
            return []

        returned_by_product = order._cod_returned_qty_by_product()
        rows = []
        for line in order.lines.filtered(lambda l: l.qty > 0).sorted(lambda l: l.id):
            product_id = line.product_id.id
            already_returned = min(float(line.qty), returned_by_product.get(product_id, 0.0))
            returned_by_product[product_id] = max(round(returned_by_product.get(product_id, 0.0) - already_returned, 4), 0.0)
            rows.append({
                'id': line.id,
                'product_id': [product_id, line.product_id.display_name],
                'full_product_name': line.full_product_name or line.product_id.display_name,
                'qty': float(line.qty),
                'returned_qty': already_returned,
                'remaining_qty': max(round(float(line.qty) - already_returned, 4), 0.0),
                'price_unit': float(line.price_unit),
                'price_subtotal_incl': float(line.price_subtotal_incl),
                'discount': float(line.discount or 0.0),
            })
        return rows

    @api.model
    def collect_cod_payment(
        self,
        order_id=None,
        payment_method_id=None,
        amount=None,
        session_id=False,
        action='payment',
        order_ref=None,
        return_lines=None,
        **kwargs
    ):
        """RPC entry point called from CodOrdersScreen when the cashier clicks
        Receive Payment and confirms the amount.

        Creates DR Cash / CR COD AR entry, reconciles, marks order paid.

        Returns:
            dict: {success: bool, message: str, order_name: str}
        """
        payload = order_id if isinstance(order_id, dict) else kwargs
        if payload:
            order_id = (
                payload.get('order_id')
                or payload.get('orderId')
                or payload.get('id')
                or payload.get('server_id')
                or payload.get('serverId')
                or order_id
            )
            payment_method_id = (
                payload.get('payment_method_id')
                or payload.get('paymentMethodId')
                or payment_method_id
            )
            amount = payload.get('amount', amount)
            session_id = payload.get('session_id') or payload.get('sessionId') or session_id
            action = payload.get('action') or action
            order_ref = (
                payload.get('order_ref')
                or payload.get('orderRef')
                or payload.get('name')
                or payload.get('pos_reference')
                or payload.get('posReference')
                or order_ref
            )

        _logger.info(
            '%s collect_cod_payment: order_id=%s order_ref=%s method_id=%s amount=%s session_id=%s action=%s',
            _COD, order_id, order_ref, payment_method_id, amount, session_id, action,
        )

        if not order_id and not order_ref:
            return {'success': False, 'message': 'Missing COD order reference. Please refresh the POS and try again.'}

        order = self.browse(int(order_id)) if order_id else self.browse()
        if order_ref and (not order.exists() or not order.is_cod):
            fallback_order = self.search([
                ('is_cod', '=', True),
                ('cod_state', 'in', ('pending', 'partial')),
                '|',
                ('name', '=', order_ref),
                ('pos_reference', '=', order_ref),
            ], limit=1)
            if fallback_order:
                _logger.warning(
                    '%s collect_cod_payment: frontend id %s resolved to %s/%s; using COD reference %s -> id %s.',
                    _COD,
                    order_id,
                    order.name if order.exists() else False,
                    order.is_cod if order.exists() else False,
                    order_ref,
                    fallback_order.id,
                )
                order = fallback_order

        if not order.exists():
            return {'success': False, 'message': 'COD order not found (id=%s, ref=%s).' % (order_id, order_ref or '')}

        if not order.is_cod:
            return {
                'success': False,
                'message': 'Order %s is not a COD order. Refresh POS, then open Pending COD Orders again.' % order.name,
            }

        if order.cod_state not in ('pending', 'partial'):
            return {
                'success': False,
                'message': 'Order %s is not open for COD collection (current state: %s).' % (order.name, order.cod_state),
            }

        if not order.partner_id:
            return {'success': False, 'message': 'COD order %s has no customer.' % order.name}

        try:
            payment_method = self.env['pos.payment.method'].browse(int(payment_method_id))
            if not payment_method.exists():
                return {'success': False, 'message': 'Payment method id=%s not found.' % payment_method_id}

            collection_session = self.env['pos.session'].browse(int(session_id)) if session_id else self.env['pos.session']
            if not collection_session or not collection_session.exists():
                return {'success': False, 'message': 'Current POS session not found. Please refresh the POS and try again.'}

            if collection_session.state not in ('opened', 'closing_control'):
                return {
                    'success': False,
                    'message': 'Session %s is not open for COD collection.' % collection_session.name,
                }

            if payment_method not in collection_session.config_id.payment_method_ids:
                return {
                    'success': False,
                    'message': 'Payment method "%s" is not configured on terminal "%s".' % (
                        payment_method.name, collection_session.config_id.display_name,
                    ),
                }

            if payment_method.type == 'pay_later':
                return {'success': False, 'message': 'Pay Later cannot be used to collect COD payments.'}

            payment_amount = round(float(amount), 2)
            order_total = round(order.amount_total, 2)
            open_amount = order._cod_open_amount()

            if payment_amount <= 0:
                return {'success': False, 'message': 'Amount must be greater than zero.'}

            if payment_amount - open_amount > 0.01:
                return {
                    'success': False,
                    'message': 'Amount %.2f exceeds the open COD balance %.2f.' % (payment_amount, open_amount),
                }

            normalized_return_lines = []
            if action == 'return':
                remaining_qty_by_product = order._cod_remaining_qty_by_product()
                normalized_return_lines = order._cod_normalize_return_lines(return_lines)
                if not normalized_return_lines:
                    normalized_return_lines = [
                        {'product_id': product_id, 'qty': qty}
                        for product_id, qty in remaining_qty_by_product.items()
                        if qty > 0
                    ]

                if not normalized_return_lines:
                    return {'success': False, 'message': 'There are no remaining COD products to return.'}

                for item in normalized_return_lines:
                    product_id = item['product_id']
                    requested_qty = item['qty']
                    remaining_qty = remaining_qty_by_product.get(product_id, 0.0)
                    if requested_qty - remaining_qty > 0.0001:
                        product = self.env['product.product'].browse(product_id)
                        return {
                            'success': False,
                            'message': 'Return quantity %.4f exceeds remaining quantity %.4f for %s.' % (
                                requested_qty,
                                remaining_qty,
                                product.display_name or product_id,
                            ),
                        }

            journal = payment_method.journal_id
            if not journal:
                return {
                    'success': False,
                    'message': 'Payment method "%s" has no journal configured.' % payment_method.name,
                }

            cod_ar_account = order._cod_get_ar_account()
            company = order.company_id or self.env.company
            commercial_partner = order.partner_id.commercial_partner_id
            cash_account = journal.default_account_id

            if not cash_account:
                return {
                    'success': False,
                    'message': 'Journal "%s" has no default account.' % journal.name,
                }

            if action == 'return':
                move = order._cod_create_return_entry(payment_amount, journal)
                entry_kind = 'return'
            else:
                move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': fields.Date.context_today(self),
                'ref': 'COD-PAY-%s' % order.name,
                'narration': 'COD Payment: %s | %s' % (order.name, order.partner_id.name),
                'is_cod_entry': False,
                'company_id': company.id,
                'line_ids': [
                    (0, 0, {
                        'account_id': cash_account.id,
                        'name': 'COD Payment received — %s' % order.name,
                        'debit': payment_amount,
                        'credit': 0.0,
                        'partner_id': commercial_partner.id,
                    }),
                    (0, 0, {
                        'account_id': cod_ar_account.id,
                        'name': 'COD Receivable cleared — %s' % order.name,
                        'debit': 0.0,
                        'credit': payment_amount,
                        'partner_id': commercial_partner.id,
                    }),
                ],
                })
                entry_kind = 'payment'
            move.action_post()

            _logger.info(
                '%s collect_cod_payment: %s entry %s posted for order %s',
                _COD, entry_kind, move.name, order.name,
            )

            # Reconcile with confirmation entry
            if order.cod_ar_move_id:
                ar_debit = order.cod_ar_move_id.line_ids.filtered(
                    lambda l: l.account_id == cod_ar_account and l.debit > 0
                )
                ar_credit = move.line_ids.filtered(
                    lambda l: l.account_id == cod_ar_account and l.credit > 0
                )
                if ar_debit and ar_credit:
                    (ar_debit + ar_credit).reconcile()
                    _logger.info('%s collect_cod_payment: AR reconciled for order %s', _COD, order.name)
                else:
                    _logger.warning(
                        '%s collect_cod_payment: AR lines not found for reconciliation on order %s '
                        '(ar_debit=%s ar_credit=%s)',
                        _COD, order.name, bool(ar_debit), bool(ar_credit),
                    )
            else:
                _logger.warning(
                    '%s collect_cod_payment: no cod_ar_move_id on order %s — '
                    'payment entry posted but not reconciled.',
                    _COD, order.name,
                )

            remaining = round(order._cod_open_amount() - payment_amount, 2)
            new_state = 'paid' if remaining <= 0.01 else 'partial'
            if action == 'return' and remaining <= 0.01:
                new_state = 'returned'
            order.write({
                'cod_state': new_state,
                'state': 'paid',
                'cod_payment_move_id': move.id,
                'cod_collection_session_id': collection_session.id,
                'cod_collection_payment_method_id': payment_method.id,
                'cod_collection_amount': order._cod_paid_total() + (payment_amount if action != 'return' else 0.0),
            })
            self.env['pos.cod.collection'].create({
                'order_id': order.id,
                'session_id': collection_session.id,
                'payment_method_id': payment_method.id,
                'move_id': move.id,
                'kind': entry_kind,
                'amount': payment_amount,
                'return_line_qtys': normalized_return_lines if action == 'return' else False,
                'note': 'COD %s via %s' % (entry_kind, payment_method.name),
            })

            if action == 'return':
                picking = order._cod_create_return_picking(return_lines=normalized_return_lines)
                if not picking:
                    raise UserError('COD return stock picking was not created. Verify the returned products are stockable.')

            _logger.info(
                '%s collect_cod_payment: order %s PAID via %s amount=%.2f session=%s',
                _COD, order.name, payment_method.name, payment_amount, collection_session.name,
            )

            return {
                'success': True,
                'message': 'COD order %s marked as paid.' % order.name,
                'order_name': order.name,
                'amount': payment_amount,
                'remaining': max(remaining, 0.0),
                'cod_state': new_state,
            }

        except Exception as exc:
            self.env.cr.rollback()
            _logger.error(
                '%s collect_cod_payment: FAILED for order_id=%s: %s',
                _COD, order_id, exc, exc_info=True,
            )
            return {'success': False, 'message': 'Server error: %s' % str(exc)}

    # ── Stock picking ─────────────────────────────────────────────────────────

    def _cod_validate_picking(self):
        """Create and immediately validate the outgoing stock picking for a COD order.

        Called at dispatch time so inventory is reduced before delivery leaves.
        Safe to call multiple times — skips if picking already done.
        """
        self.ensure_one()
        _logger.info('%s _cod_validate_picking: order %s', _COD, self.name)

        existing_done = self.picking_ids.filtered(lambda p: p.state == 'done')
        if existing_done:
            _logger.info(
                '%s _cod_validate_picking: picking already done for order %s (%s) — skipping.',
                _COD, self.name, existing_done.mapped('name'),
            )
            return

        try:
            self._create_order_picking()

            all_pickings = self.picking_ids
            _logger.info(
                '%s _cod_validate_picking: pickings after creation for order %s: %s',
                _COD, self.name,
                [(p.name, p.state) for p in all_pickings],
            )

            pending = all_pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                _logger.warning(
                    '%s _cod_validate_picking: no pending picking after creation for order %s '
                    '(service-only order or stock not tracked).',
                    _COD, self.name,
                )
                return

            for pick in pending:
                if pick.state in ('draft', 'confirmed'):
                    pick.action_confirm()

                pick.action_assign()

                _logger.info(
                    '%s _cod_validate_picking: pick %s state after assign=%s moves=%s',
                    _COD, pick.name, pick.state,
                    [(m.product_id.name, m.state, len(m.move_line_ids)) for m in pick.move_ids],
                )

                # Force-create move lines for any moves that could not be reserved,
                # allowing COD dispatch even when on-hand stock is zero or negative.
                for move in pick.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel', 'assigned')
                ):
                    _logger.info(
                        '%s _cod_validate_picking: force-assigning move %s (product=%s qty=%s)',
                        _COD, move.id, move.product_id.name, move.product_uom_qty,
                    )
                    if not move.move_line_ids:
                        self.env['stock.move.line'].create({
                            'move_id': move.id,
                            'picking_id': pick.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'quantity': move.product_uom_qty,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                        })
                    # Write state directly — readonly=True is UI-only, ORM allows it.
                    move.sudo().write({'state': 'assigned'})

                # Set done qty on all pending move lines.
                for move in pick.move_ids:
                    if move.state in ('done', 'cancel'):
                        continue
                    for ml in move.move_line_ids:
                        ml.quantity = ml.quantity or move.product_uom_qty
                pick.move_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')
                ).write({'picked': True})

                _logger.info(
                    '%s _cod_validate_picking: calling _action_done for pick %s state=%s',
                    _COD, pick.name, pick.state,
                )
                # Use _action_done directly to bypass button_validate pre-hooks.
                # cod_dispatch=True tells our StockQuant override to allow the
                # quant to go negative (Option C / l10n_ke_edi_oscu_stock bypass).
                pick.with_context(
                    skip_backorder=True,
                    cancel_backorder=True,
                    cod_dispatch=True,
                )._action_done()

                _logger.info(
                    '%s _cod_validate_picking: picking %s validated for order %s.',
                    _COD, pick.name, self.name,
                )

        except UserError as exc:
            _logger.warning(
                '%s _cod_validate_picking: UserError for order %s: %s',
                _COD, self.name, exc,
            )
            raise
        except Exception as exc:
            _logger.error(
                '%s _cod_validate_picking: FAILED for order %s: %s',
                _COD, self.name, exc, exc_info=True,
            )
            raise UserError(
                'COD stock dispatch failed for order %s:\n%s\n\n'
                'Check stock levels and product configurations.' % (self.name, str(exc))
            )

    def _create_order_picking(self):
        """Override: skip picking creation for COD orders that are already dispatched."""
        if self.is_cod:
            done = self.picking_ids.filtered(lambda p: p.state == 'done')
            if done:
                _logger.info(
                    '%s _create_order_picking: skipping — COD order %s already has '
                    'a done picking (%s).',
                    _COD, self.name, done.mapped('name'),
                )
                return True
            # Inject cod_dispatch so any _action_done calls triggered inside the
            # standard POS picking-creation flow (e.g. by paint_tinting) also
            # bypass the l10n_ke_edi_oscu_stock negative-stock constraint.
            return super(PosOrder, self.with_context(cod_dispatch=True))._create_order_picking()
        return super()._create_order_picking()

    # ── Accounting ─────────────────────────────────────────────────────────────

    def _cod_post_ar_entry(self):
        """Post the COD confirmation journal entry: DR COD AR / CR Sales / CR Tax.

        Uses the dedicated COD AR account (asset_receivable, reconcile=True) so:
          - The entry is excluded from pos_credit_limit credit-limit checks.
          - Odoo's reconciliation engine can match it against the payment entry.
          - Aged AR reports show COD receivables on a separate account row.

        Revenue and tax accounts are resolved per product line.
        A rounding adjustment (≤ 0.01) is applied to the last credit line if needed
        so that debits = credits exactly.
        """
        self.ensure_one()
        amount_untaxed = round(float(self.amount_total - self.amount_tax), 2)
        _logger.info(
            '%s _cod_post_ar_entry: order=%s total=%.2f tax=%.2f untaxed=%.2f',
            _COD, self.name, self.amount_total, self.amount_tax, amount_untaxed,
        )

        cod_ar_account = self._cod_get_ar_account()
        sales_journal = self._cod_get_sales_journal()
        company = self.company_id or self.env.company
        commercial_partner = self.partner_id.commercial_partner_id

        move_lines = []
        credit_total = 0.0

        # ── Revenue lines (CR per product, tax-exclusive) ─────────────────────
        for line in self.lines:
            income_account = (
                line.product_id.with_company(company).property_account_income_id
                or line.product_id.categ_id.with_company(company).property_account_income_categ_id
            )
            if not income_account:
                raise UserError(
                    'Product "%s" has no income account configured. '
                    'Set it on the product or its category before dispatching as COD.'
                    % line.product_id.name
                )

            amount = round(float(line.price_subtotal), 2)
            move_lines.append((0, 0, {
                'account_id': income_account.id,
                'name': '%s (COD %s)' % (line.product_id.name, self.name),
                'debit': 0.0,
                'credit': amount,
                'partner_id': commercial_partner.id,
                'quantity': float(line.qty),
            }))
            credit_total += amount
            _logger.debug(
                '%s _cod_post_ar_entry: revenue line — product=%s account=%s amount=%.2f',
                _COD, line.product_id.name, income_account.name, amount,
            )

        # ── Tax lines (CR per tax account) ────────────────────────────────────
        if self.amount_tax:
            tax_buckets = {}
            for line in self.lines:
                if not line.tax_ids:
                    continue
                taxes_calc = line.tax_ids.compute_all(
                    float(line.price_unit),
                    currency=self.currency_id,
                    quantity=float(line.qty),
                    product=line.product_id,
                    partner=self.partner_id,
                )
                for t in taxes_calc.get('taxes', []):
                    tax_obj = self.env['account.tax'].browse(t['id'])
                    tax_account = None
                    for rep in tax_obj.invoice_repartition_line_ids:
                        if rep.repartition_type == 'tax' and rep.account_id:
                            tax_account = rep.account_id
                            break
                    if tax_account:
                        tax_buckets[tax_account.id] = tax_buckets.get(tax_account.id, 0.0) + t['amount']
                    else:
                        _logger.warning(
                            '%s _cod_post_ar_entry: tax "%s" has no repartition account '
                            '— tax amount folded into revenue for order %s.',
                            _COD, tax_obj.name, self.name,
                        )

            for acct_id, tax_amt in tax_buckets.items():
                amt = round(tax_amt, 2)
                move_lines.append((0, 0, {
                    'account_id': acct_id,
                    'name': 'Tax — COD %s' % self.name,
                    'debit': 0.0,
                    'credit': amt,
                    'partner_id': commercial_partner.id,
                }))
                credit_total += amt
                _logger.debug(
                    '%s _cod_post_ar_entry: tax line — account_id=%s amount=%.2f',
                    _COD, acct_id, amt,
                )

        # ── Rounding adjustment ───────────────────────────────────────────────
        ar_debit = round(self.amount_total, 2)
        rounding_diff = round(ar_debit - credit_total, 2)
        if abs(rounding_diff) > 0.0001 and move_lines:
            last = dict(move_lines[-1][2])
            last['credit'] = round(last['credit'] + rounding_diff, 2)
            move_lines[-1] = (0, 0, last)
            _logger.debug(
                '%s _cod_post_ar_entry: rounding adjustment %.4f applied.', _COD, rounding_diff,
            )

        # ── AR debit line ─────────────────────────────────────────────────────
        move_lines.insert(0, (0, 0, {
            'account_id': cod_ar_account.id,
            'name': 'COD Receivable — %s' % self.name,
            'debit': ar_debit,
            'credit': 0.0,
            'partner_id': commercial_partner.id,
        }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': sales_journal.id,
            'date': fields.Date.context_today(self),
            'ref': 'COD-CONF-%s' % self.name,
            'narration': 'COD Dispatch Confirmation | %s | Customer: %s' % (
                self.name, self.partner_id.name,
            ),
            'is_cod_entry': True,
            'company_id': company.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.cod_ar_move_id = move

        _logger.info(
            '%s _cod_post_ar_entry: entry %s posted for order %s (DR COD AR=%.2f).',
            _COD, move.name, self.name, ar_debit,
        )
        return move

    def _cod_create_payment_entry(self):
        """Create the COD payment entry: DR Cash/Bank / CR COD AR.

        Supports multiple payment methods on a single COD order.
        The entry is NOT flagged is_cod_entry=True because it is a payment,
        not a dispatch confirmation; the credit side clears the COD AR.
        """
        self.ensure_one()
        _logger.info(
            '%s _cod_create_payment_entry: order=%s payments=%s',
            _COD, self.name, [(p.payment_method_id.name, p.amount) for p in self.payment_ids],
        )

        cod_ar_account = self._cod_get_ar_account()
        company = self.company_id or self.env.company
        commercial_partner = self.partner_id.commercial_partner_id

        debit_lines = []
        total_paid = 0.0
        first_journal = None

        for payment in self.payment_ids:
            journal = payment.payment_method_id.journal_id
            if not journal:
                _logger.warning(
                    '%s _cod_create_payment_entry: method "%s" has no journal — skipping.',
                    _COD, payment.payment_method_id.name,
                )
                continue
            cash_account = journal.default_account_id
            if not cash_account:
                _logger.warning(
                    '%s _cod_create_payment_entry: journal "%s" has no default account — skipping.',
                    _COD, journal.name,
                )
                continue
            if not first_journal:
                first_journal = journal
            debit_lines.append((0, 0, {
                'account_id': cash_account.id,
                'name': 'COD Payment (%s) — %s' % (payment.payment_method_id.name, self.name),
                'debit': round(payment.amount, 2),
                'credit': 0.0,
                'partner_id': commercial_partner.id,
            }))
            total_paid += payment.amount
            _logger.debug(
                '%s _cod_create_payment_entry: debit line — journal=%s amount=%.2f',
                _COD, journal.name, payment.amount,
            )

        if not first_journal:
            raise UserError(
                'No valid journal found for any payment method on COD order %s. '
                'Ensure payment methods have journals configured.' % self.name
            )

        credit_line = (0, 0, {
            'account_id': cod_ar_account.id,
            'name': 'COD Receivable cleared — %s' % self.name,
            'debit': 0.0,
            'credit': round(total_paid, 2),
            'partner_id': commercial_partner.id,
        })

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': first_journal.id,
            'date': fields.Date.context_today(self),
            'ref': 'COD-PAY-%s' % self.name,
            'narration': 'COD Payment Collection | %s | %s' % (self.name, self.partner_id.name),
            'is_cod_entry': False,
            'company_id': company.id,
            'line_ids': debit_lines + [credit_line],
        })
        move.action_post()

        _logger.info(
            '%s _cod_create_payment_entry: entry %s posted for order %s (total_paid=%.2f).',
            _COD, move.name, self.name, total_paid,
        )
        return move

    def _cod_reconcile(self, payment_entry):
        """Reconcile the COD AR debit (confirmation) with the COD AR credit (payment)."""
        self.ensure_one()

        if not self.cod_ar_move_id:
            _logger.warning(
                '%s _cod_reconcile: no cod_ar_move_id on order %s — cannot reconcile.',
                _COD, self.name,
            )
            return

        cod_ar_account = self._cod_get_ar_account()

        ar_debit = self.cod_ar_move_id.line_ids.filtered(
            lambda l: l.account_id == cod_ar_account and l.debit > 0
        )
        ar_credit = payment_entry.line_ids.filtered(
            lambda l: l.account_id == cod_ar_account and l.credit > 0
        )

        _logger.debug(
            '%s _cod_reconcile: ar_debit lines=%s ar_credit lines=%s',
            _COD, len(ar_debit), len(ar_credit),
        )

        if not ar_debit or not ar_credit:
            _logger.error(
                '%s _cod_reconcile: AR lines missing for order %s — '
                'confirmation entry: %s | payment entry: %s',
                _COD, self.name, self.cod_ar_move_id.name, payment_entry.name,
            )
            return

        (ar_debit + ar_credit).reconcile()
        _logger.info('%s _cod_reconcile: AR reconciled for order %s.', _COD, self.name)

    def _cod_create_return_entry(self, amount, journal):
        """Reverse part/all of the COD sale and clear the same COD AR."""
        self.ensure_one()
        cod_ar_account = self._cod_get_ar_account()
        company = self.company_id or self.env.company
        commercial_partner = self.partner_id.commercial_partner_id
        ratio = amount / self.amount_total if self.amount_total else 1.0

        lines = [(0, 0, {
            'account_id': cod_ar_account.id,
            'name': 'COD Receivable returned - %s' % self.name,
            'debit': 0.0,
            'credit': amount,
            'partner_id': commercial_partner.id,
        })]
        debit_total = 0.0
        for source in self.cod_ar_move_id.line_ids.filtered(lambda l: l.credit > 0):
            debit = round(source.credit * ratio, 2)
            if not debit:
                continue
            lines.append((0, 0, {
                'account_id': source.account_id.id,
                'name': 'COD Return - %s' % (source.name or self.name),
                'debit': debit,
                'credit': 0.0,
                'partner_id': commercial_partner.id,
            }))
            debit_total += debit
        diff = round(amount - debit_total, 2)
        if lines[1:] and abs(diff) > 0.0001:
            last = dict(lines[-1][2])
            last['debit'] = round(last['debit'] + diff, 2)
            lines[-1] = (0, 0, last)

        return self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': 'COD-RET-%s' % self.name,
            'narration': 'COD Return: %s | %s' % (self.name, self.partner_id.name),
            'is_cod_entry': False,
            'company_id': company.id,
            'line_ids': lines,
        })

    def _cod_create_return_picking(self, return_lines=None):
        """Create and validate a return picking for a COD order.

        return_lines: list of {'product_id': id, 'qty': n} from CodReturnDialog.
                      When empty/None, all storable lines are returned at full qty.
        """
        self.ensure_one()
        try:
            if not self.session_id or not self.session_id.config_id.picking_type_id:
                return False

            # Build product_id -> return_qty map from the per-line selection.
            # Fall back to full quantities when the caller passes no lines.
            if return_lines:
                qty_map = {int(rl['product_id']): float(rl['qty']) for rl in return_lines if rl.get('qty', 0) > 0}
            else:
                qty_map = {line.product_id.id: line.qty for line in self.lines if line.qty > 0}

            source_location = self.partner_id.property_stock_customer
            pos_picking_type = self.session_id.config_id.picking_type_id
            picking_type = pos_picking_type.return_picking_type_id or pos_picking_type
            if pos_picking_type.return_picking_type_id and picking_type.default_location_dest_id:
                dest_location = picking_type.default_location_dest_id
            else:
                dest_location = pos_picking_type.default_location_src_id

            if not source_location or not dest_location or source_location == dest_location:
                raise UserError(
                    'COD return stock locations are invalid for order %s. '
                    'Source=%s, Destination=%s. Configure the POS return operation or POS source location.'
                    % (
                        self.name,
                        source_location.display_name if source_location else 'Missing',
                        dest_location.display_name if dest_location else 'Missing',
                    )
                )

            moves = []
            qty_left_by_product = dict(qty_map)
            # Only storable products affect stock and trigger valuation entries.
            for line in self.lines.filtered(lambda l: l.product_id.is_storable and l.qty > 0):
                requested_qty = qty_left_by_product.get(line.product_id.id, 0.0)
                qty = round(min(requested_qty, float(line.qty)), 4)
                if qty <= 0:
                    continue
                qty_left_by_product[line.product_id.id] = round(requested_qty - qty, 4)
                moves.append((0, 0, {
                    'name': 'COD Return %s' % line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': qty,
                    'product_uom': line.product_id.uom_id.id,
                    'location_id': source_location.id,
                    'location_dest_id': dest_location.id,
                }))

            if not moves:
                _logger.info('%s _cod_create_return_picking: no storable lines to return for order %s', _COD, self.name)
                return False

            picking = self.env['stock.picking'].create({
                'partner_id': self.partner_id.id,
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': dest_location.id,
                'origin': 'COD Return %s' % self.name,
                'pos_order_id': self.id,
                'pos_session_id': self.session_id.id,
                'move_ids': moves,
            })
            picking.action_confirm()

            # Build lot map for lot/serial-tracked products.
            # Strategy 1: scan done dispatch pickings (move lines going away from
            # the warehouse, i.e. NOT towards the warehouse dest).
            # Strategy 2: fall back to pack_lot_ids on the POS order lines, which
            # always store the lot names selected at the time of sale.
            lot_map = {}  # product_id -> [(stock.lot record, qty)]
            done_pickings = self.picking_ids.filtered(lambda p: p.state == 'done')
            for op in done_pickings:
                for ml in op.move_line_ids:
                    if ml.lot_id and ml.location_dest_id.usage == 'customer':
                        lot_map.setdefault(ml.product_id.id, []).append((ml.lot_id, ml.quantity))

            if not lot_map:
                # Fallback: resolve lot names from POS order line pack_lot_ids
                company = self.company_id or self.env.company
                for line in self.lines.filtered(lambda l: l.product_id.is_storable and l.qty > 0):
                    if line.product_id.tracking == 'none':
                        continue
                    for pack_lot in line.pack_lot_ids:
                        if not pack_lot.lot_name:
                            continue
                        lot = self.env['stock.lot'].search([
                            ('name', '=', pack_lot.lot_name),
                            ('product_id', '=', line.product_id.id),
                            ('company_id', '=', company.id),
                        ], limit=1)
                        if lot:
                            qty = 1.0 if line.product_id.tracking == 'serial' else float(line.qty)
                            lot_map.setdefault(line.product_id.id, []).append((lot, qty))

            _logger.info(
                '%s _cod_create_return_picking: lot_map=%s (done_pickings=%d)',
                _COD,
                {pid: [(l.name, q) for l, q in vals] for pid, vals in lot_map.items()},
                len(done_pickings),
            )

            for move in picking.move_ids:
                move.move_line_ids.unlink()
                pid = move.product_id.id
                qty_to_return = move.product_uom_qty
                lots = lot_map.get(pid, [])

                if lots and move.product_id.tracking != 'none':
                    qty_left = qty_to_return
                    for lot, lot_qty in lots:
                        if qty_left <= 0:
                            break
                        use_qty = round(min(lot_qty, qty_left), 4)
                        self.env['stock.move.line'].create({
                            'picking_id': picking.id,
                            'move_id': move.id,
                            'product_id': pid,
                            'product_uom_id': move.product_uom.id,
                            'quantity': use_qty,
                            'location_id': source_location.id,
                            'location_dest_id': dest_location.id,
                            'lot_id': lot.id,
                        })
                        qty_left = round(qty_left - use_qty, 4)
                else:
                    self.env['stock.move.line'].create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': pid,
                        'product_uom_id': move.product_uom.id,
                        'quantity': qty_to_return,
                        'location_id': source_location.id,
                        'location_dest_id': dest_location.id,
                    })
            picking.move_ids.write({'picked': True})
            picking.with_context(cancel_backorder=True)._action_done()
            _logger.info('%s _cod_create_return_picking: validated picking %s for order %s', _COD, picking.name, self.name)
            return picking
        except Exception as exc:
            _logger.warning(
                '%s _cod_create_return_picking: stock return failed for %s lines=%s: %s',
                _COD, self.name, return_lines, exc,
                exc_info=True,
            )
            raise

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cod_get_ar_account(self):
        """Return the configured COD AR account for this order's company.

        Lookup priority:
          1. The pos.config linked to this order's session
          2. Any pos.config for the same company with a COD AR account set
        Raises UserError if none is found (prevents silent accounting corruption).
        """
        company = self.company_id or self.env.company

        config = self.session_id.config_id if self.session_id else None
        if config and config.cod_ar_account_id:
            return config.cod_ar_account_id

        config = self.env['pos.config'].search(
            [('company_id', '=', company.id), ('cod_ar_account_id', '!=', False)],
            limit=1,
        )
        if config:
            return config.cod_ar_account_id

        raise UserError(
            'No COD Receivable Account configured for company "%s". '
            'Set it in POS Configuration → COD Settings before dispatching COD orders.'
            % company.name
        )

    def _cod_get_sales_journal(self):
        """Return the sales journal for COD accounting entries."""
        company = self.company_id or self.env.company
        journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)],
            limit=1,
        )
        if not journal:
            raise UserError(
                'No sales journal found for company "%s". '
                'COD requires a sales journal to post the dispatch entry.' % company.name
            )
        return journal
