# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

_COD_DISCOUNT = '[COD][Discount]'


class PosCodCollection(models.Model):
    _inherit = 'pos.cod.collection'

    kind = fields.Selection(
        selection_add=[('discount', 'Discount')],
        ondelete={'discount': 'cascade'},
    )


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cod_amount_discount = fields.Monetary(
        string='COD Discount',
        currency_field='currency_id',
        compute='_compute_cod_amounts',
    )

    @api.depends('amount_total', 'cod_collection_ids.amount', 'cod_collection_ids.kind')
    def _compute_cod_amounts(self):
        for order in self:
            paid = sum(order.cod_collection_ids.filtered(lambda c: c.kind == 'payment').mapped('amount'))
            returned = sum(order.cod_collection_ids.filtered(lambda c: c.kind == 'return').mapped('amount'))
            discount = sum(order.cod_collection_ids.filtered(lambda c: c.kind == 'discount').mapped('amount'))
            order.cod_amount_paid = paid
            order.cod_amount_returned = returned
            order.cod_amount_discount = discount
            order.cod_amount_open = max(round(order.amount_total - paid - returned - discount, 2), 0.0)

    def _cod_discount_total(self):
        self.ensure_one()
        return sum(self.cod_collection_ids.filtered(lambda c: c.kind == 'discount').mapped('amount'))

    def _cod_open_amount(self):
        self.ensure_one()
        return max(
            round(
                self.amount_total
                - self._cod_paid_total()
                - self._cod_return_total()
                - self._cod_discount_total(),
                2,
            ),
            0.0,
        )

    def _cod_discount_remaining_profit_vat_incl(self):
        self.ensure_one()
        returned_by_product = self._cod_returned_qty_by_product()
        currency = self.currency_id
        profit = 0.0

        for line in self.lines.filtered(lambda l: l.qty > 0).sorted(lambda l: l.id):
            product = line.product_id
            product_id = product.id
            already_returned = min(float(line.qty), returned_by_product.get(product_id, 0.0))
            returned_by_product[product_id] = max(
                round(returned_by_product.get(product_id, 0.0) - already_returned, 4),
                0.0,
            )
            remaining_qty = max(round(float(line.qty) - already_returned, 4), 0.0)
            if remaining_qty <= 0:
                continue

            selling_incl = float(line.price_subtotal_incl or 0.0) / float(line.qty)
            cost_excl = product.standard_price or 0.0
            if line.tax_ids:
                cost_incl = line.tax_ids.compute_all(
                    cost_excl,
                    currency=currency,
                    quantity=1.0,
                    product=product,
                    partner=self.partner_id,
                    handle_price_include=False,
                )['total_included']
            else:
                cost_incl = cost_excl

            line_profit = (selling_incl - cost_incl) * remaining_qty
            profit += line_profit
            _logger.info(
                '%s remaining-profit line order=%s product=%s remaining_qty=%.4f '
                'selling_incl=%.4f cost_incl=%.4f line_profit=%.4f',
                _COD_DISCOUNT,
                self.name,
                product.display_name,
                remaining_qty,
                selling_incl,
                cost_incl,
                line_profit,
            )

        remaining_profit = round(profit - self._cod_discount_total(), 2)
        _logger.info(
            '%s remaining-profit summary order=%s gross_profit=%.4f existing_discount=%.4f '
            'remaining_profit=%.4f open_amount=%.4f',
            _COD_DISCOUNT,
            self.name,
            profit,
            self._cod_discount_total(),
            remaining_profit,
            self._cod_open_amount(),
        )
        return max(remaining_profit, 0.0)

    def _cod_validate_discount_amount(self, amount):
        self.ensure_one()
        currency = self.currency_id
        precision = currency.rounding or 0.01
        discount_amount = round(float(amount or 0.0), 2)
        open_amount = self._cod_open_amount()
        remaining_profit = self._cod_discount_remaining_profit_vat_incl()

        if discount_amount <= 0:
            return {
                'allowed': False,
                'reason': 'non_positive',
                'message': 'Discount amount must be greater than zero.',
                'amount': discount_amount,
                'open_amount': open_amount,
                'remaining_profit': remaining_profit,
            }

        if float_compare(discount_amount, open_amount, precision_rounding=precision) > 0:
            return {
                'allowed': False,
                'reason': 'exceeds_open',
                'message': 'Discount %.2f exceeds the open COD receivable %.2f.' % (
                    discount_amount,
                    open_amount,
                ),
                'amount': discount_amount,
                'open_amount': open_amount,
                'remaining_profit': remaining_profit,
            }

        if float_compare(discount_amount, remaining_profit, precision_rounding=precision) > 0:
            return {
                'allowed': False,
                'reason': 'exceeds_profit',
                'message': 'Discount %.2f exceeds remaining order profit %.2f.' % (
                    discount_amount,
                    remaining_profit,
                ),
                'amount': discount_amount,
                'open_amount': open_amount,
                'remaining_profit': remaining_profit,
            }

        return {
            'allowed': True,
            'reason': 'ok',
            'message': 'Discount is within remaining profit and open receivable.',
            'amount': discount_amount,
            'open_amount': open_amount,
            'remaining_profit': remaining_profit,
        }

    def _cod_create_discount_entry(self, amount, collection_session):
        self.ensure_one()
        cod_ar_account = self._cod_get_ar_account()
        journal = self._cod_get_sales_journal()
        company = self.company_id or self.env.company
        commercial_partner = self.partner_id.commercial_partner_id
        ratio = amount / self.amount_total if self.amount_total else 1.0

        lines = [(0, 0, {
            'account_id': cod_ar_account.id,
            'name': 'COD Discount - %s' % self.name,
            'debit': 0.0,
            'credit': amount,
            'partner_id': commercial_partner.id,
        })]
        debit_total = 0.0
        source_lines = self.cod_ar_move_id.line_ids.filtered(lambda l: l.credit > 0)
        for source in source_lines:
            debit = round(source.credit * ratio, 2)
            if not debit:
                continue
            lines.append((0, 0, {
                'account_id': source.account_id.id,
                'name': 'COD Discount - %s' % (source.name or self.name),
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

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': 'COD-DISC-%s' % self.name,
            'narration': 'COD Discount: %s | %s | Session: %s' % (
                self.name,
                self.partner_id.name,
                collection_session.name,
            ),
            'is_cod_entry': False,
            'company_id': company.id,
            'line_ids': lines,
        })
        move.action_post()
        _logger.info(
            '%s discount entry posted order=%s move=%s amount=%.2f ratio=%.6f',
            _COD_DISCOUNT,
            self.name,
            move.name,
            amount,
            ratio,
        )
        return move

    @api.model
    def apply_cod_discount(self, payload):
        order_id = payload.get('order_id') or payload.get('orderId')
        order_ref = payload.get('order_ref') or payload.get('orderRef')
        session_id = payload.get('session_id') or payload.get('sessionId')
        amount = payload.get('amount')

        _logger.info(
            '%s apply request order_id=%s order_ref=%s session_id=%s amount=%s payload=%s',
            _COD_DISCOUNT,
            order_id,
            order_ref,
            session_id,
            amount,
            payload,
        )

        order = self.browse(int(order_id)) if order_id else self.browse()
        if order_ref and (not order.exists() or not order.is_cod):
            order = self.search([
                ('is_cod', '=', True),
                ('cod_state', 'in', ('pending', 'partial')),
                '|',
                ('name', '=', order_ref),
                ('pos_reference', '=', order_ref),
            ], limit=1)

        if not order.exists():
            return {'success': False, 'message': 'COD order not found.'}
        if not order.is_cod:
            return {'success': False, 'message': 'Order %s is not a COD order.' % order.name}
        if order.cod_state not in ('pending', 'partial'):
            return {
                'success': False,
                'message': 'Order %s is not open for COD discount (current state: %s).' % (
                    order.name,
                    order.cod_state,
                ),
            }
        if not order.cod_ar_move_id:
            return {'success': False, 'message': 'COD order %s has no receivable entry.' % order.name}

        collection_session = self.env['pos.session'].browse(int(session_id)) if session_id else self.env['pos.session']
        if not collection_session or not collection_session.exists():
            return {'success': False, 'message': 'Current POS session not found. Please refresh POS.'}
        if collection_session.state not in ('opened', 'closing_control'):
            return {'success': False, 'message': 'Session %s is not open.' % collection_session.name}

        validation = order._cod_validate_discount_amount(amount)
        if not validation['allowed']:
            _logger.warning('%s blocked order=%s validation=%s', _COD_DISCOUNT, order.name, validation)
            return {'success': False, **validation}

        try:
            discount_amount = validation['amount']
            move = order._cod_create_discount_entry(discount_amount, collection_session)
            cod_ar_account = order._cod_get_ar_account()
            if order.cod_ar_move_id:
                ar_debit = order.cod_ar_move_id.line_ids.filtered(
                    lambda l: l.account_id == cod_ar_account and l.debit > 0
                )
                ar_credit = move.line_ids.filtered(
                    lambda l: l.account_id == cod_ar_account and l.credit > 0
                )
                if ar_debit and ar_credit:
                    (ar_debit + ar_credit).reconcile()
                    _logger.info('%s AR reconciled order=%s move=%s', _COD_DISCOUNT, order.name, move.name)

            remaining = round(order._cod_open_amount() - discount_amount, 2)
            new_state = 'paid' if remaining <= 0.01 else 'partial'
            order.write({
                'cod_state': new_state,
                'state': 'paid',
                'cod_collection_session_id': collection_session.id,
            })
            self.env['pos.cod.collection'].create({
                'order_id': order.id,
                'session_id': collection_session.id,
                'payment_method_id': False,
                'move_id': move.id,
                'kind': 'discount',
                'amount': discount_amount,
                'note': 'COD discount via %s' % collection_session.name,
            })
            _logger.info(
                '%s applied order=%s amount=%.2f remaining=%.2f state=%s',
                _COD_DISCOUNT,
                order.name,
                discount_amount,
                max(remaining, 0.0),
                new_state,
            )
            return {
                'success': True,
                'message': 'COD discount %.2f applied to %s.' % (discount_amount, order.name),
                'order_name': order.name,
                'amount': discount_amount,
                'remaining': max(remaining, 0.0),
                'cod_state': new_state,
                'remaining_profit': validation['remaining_profit'] - discount_amount,
            }
        except Exception as exc:
            self.env.cr.rollback()
            _logger.error('%s apply failed order=%s: %s', _COD_DISCOUNT, order.name, exc, exc_info=True)
            return {'success': False, 'message': 'Server error: %s' % str(exc)}
