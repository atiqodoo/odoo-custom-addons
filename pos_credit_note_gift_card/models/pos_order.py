# -*- coding: utf-8 -*-
"""
pos_order.py — POS order extension for credit-note workflow
============================================================
Adds server-side methods that the gift-card credit-note controller
calls during return validation and gift-card issuance.

Public API (called by the controller)
--------------------------------------
validate_return_for_credit_note(config_id)
    Pre-flight check before any refund is committed.
    Returns a structured dict: {ok, errors, warnings, lines_info}.

compute_credit_note_amount(config_id)
    Walk every return line and compute the net gift-card amount after
    applying discount-distribution and commission-netting settings.
    Returns {total, breakdown: [{product, gross, discount_adj, commission_adj, net}]}.

create_credit_note_gift_card(config_id, amount, partner_id, reason)
    Issue a ``loyalty.card`` against the configured gift-card program
    and return its id, code, and initial_balance.

get_original_order_info(original_order_id)
    Read discount and commission summary of the original (sale) order.
    Used by the JS layer to show an advisory breakdown to the cashier.

Logging
-------
Logger : ``pos_credit_note_gift_card.pos_order``
Level  : DEBUG for computations, INFO for key business events,
         WARNING for configuration problems.
"""

import logging
from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger('pos_credit_note_gift_card.pos_order')


class PosOrder(models.Model):
    _inherit = 'pos.order'

    # =========================================================================
    # NOTE: _load_pos_data_fields is intentionally NOT overridden here.
    #
    # pos.order inherits pos.load.mixin which returns [] (all fields) by
    # default, so amount_total, amount_tax and all other standard order fields
    # are already included in the session payload automatically.
    # =========================================================================
    # Pre-flight validation
    # =========================================================================

    def validate_return_for_credit_note(self, config_id):
        """
        Validate that the current order (which must be a refund order with
        negative-qty lines) can be issued as a gift-card credit note.

        Checks performed
        ----------------
        1. Order is a refund (all lines have negative qty).
        2. None of the returned products are flagged ``pos_not_returnable``.
        3. The configured gift-card program passes its structural validation.

        Parameters
        ----------
        config_id : int

        Returns
        -------
        dict
            {
                'ok'       : bool,
                'errors'   : [str],   # blocking issues
                'warnings' : [str],   # informational
                'lines_info': [
                    {'product': str, 'qty': float, 'returnable': bool}
                ]
            }
        """
        self.ensure_one()
        errors = []
        warnings = []
        lines_info = []

        _logger.info(
            "[PosOrder][validate_return_for_credit_note] "
            "order='%s' (id=%s) | config_id=%s",
            self.name, self.id, config_id,
        )

        config = self.env['pos.config'].browse(config_id)

        # --- 1. Gift-card program validation ---
        ok_program, program_err = config._validate_credit_note_program()
        if not ok_program:
            errors.append(program_err)

        # --- 2. Check each line ---
        for line in self.lines:
            product_name = line.product_id.display_name if line.product_id else '?'
            returnable = not line.is_non_returnable()
            info = {
                'product': product_name,
                'qty': line.qty,
                'returnable': returnable,
            }
            lines_info.append(info)

            if not returnable:
                msg = _(
                    "'%(product)s' is not eligible for return or refund "
                    "(non-returnable product).",
                    product=product_name,
                )
                errors.append(msg)
                _logger.info(
                    "[PosOrder][validate_return_for_credit_note] "
                    "BLOCKED — non-returnable product: '%s'", product_name,
                )

        result = {
            'ok': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'lines_info': lines_info,
        }
        _logger.debug(
            "[PosOrder][validate_return_for_credit_note] result=%s", result,
        )
        return result

    # =========================================================================
    # Net credit-note amount computation
    # =========================================================================

    def compute_credit_note_amount(self, config_id):
        """
        Compute the net amount to load onto the gift card.

        Steps per return line
        ---------------------
        1. Gross refund amount  = abs(price_subtotal_incl)
        2. Discount adjustment  = apply discount-distribution from config
        3. Commission deduction = apply commission-netting from config
        4. Net per line         = max(0, gross - discount_adj_reduction - commission_deduction)

        The 'equal' discount mode requires a pre-computed per-line equal
        share which is calculated from the original order.

        Parameters
        ----------
        config_id : int

        Returns
        -------
        dict
            {
                'total'    : float,
                'currency' : str,
                'breakdown': [
                    {
                        'product'        : str,
                        'gross'          : float,
                        'discount_adj'   : float,  # amount removed due to discount
                        'commission_adj' : float,  # amount removed due to commission
                        'net'            : float,
                    }
                ]
            }
        """
        self.ensure_one()
        config = self.env['pos.config'].browse(config_id)
        dist_mode = config.credit_note_discount_distribution
        comm_mode = config.credit_note_commission_mode
        extra_w   = config.credit_note_extra_weight
        base_w    = config.credit_note_base_weight

        _logger.info(
            "[PosOrder][compute_credit_note_amount] order='%s' | "
            "dist_mode=%s | comm_mode=%s | extra_w=%.1f | base_w=%.1f",
            self.name, dist_mode, comm_mode, extra_w, base_w,
        )

        # Pre-compute equal discount share if needed
        equal_share_per_line = 0.0
        if dist_mode == 'equal' and self.lines:
            total_discount_amount = sum(
                abs(l.price_subtotal_incl or 0.0) * (l.discount or 0.0) / 100.0
                for l in self.lines
            )
            n_lines = len(self.lines)
            equal_share_per_line = total_discount_amount / n_lines if n_lines else 0.0
            _logger.debug(
                "[PosOrder][compute_credit_note_amount] equal mode: "
                "total_discount=%.4f | n_lines=%d | share_per_line=%.4f",
                total_discount_amount, n_lines, equal_share_per_line,
            )

        breakdown = []
        total = 0.0

        for line in self.lines:
            gross = abs(line.price_subtotal_incl or 0.0)

            # Discount adjustment
            if dist_mode == 'proportional':
                net_after_discount = line.compute_discounted_refund_amount('proportional')
                discount_adj = gross - net_after_discount
            elif dist_mode == 'equal':
                discount_adj = min(equal_share_per_line, gross)
                net_after_discount = gross - discount_adj
            else:  # 'none'
                discount_adj = 0.0
                net_after_discount = gross

            # Commission deduction
            commission_adj = line.compute_commission_deduction(comm_mode, extra_w, base_w)

            # Net
            net = max(0.0, net_after_discount - commission_adj)

            _logger.debug(
                "[PosOrder][compute_credit_note_amount] "
                "line product='%s' | gross=%.4f | discount_adj=%.4f "
                "| commission_adj=%.4f | net=%.4f",
                line.product_id.display_name if line.product_id else 'N/A',
                gross, discount_adj, commission_adj, net,
            )

            breakdown.append({
                'product':        line.product_id.display_name if line.product_id else '?',
                'gross':          gross,
                'discount_adj':   discount_adj,
                'commission_adj': commission_adj,
                'net':            net,
            })
            total += net

        currency = self.currency_id.name if self.currency_id else 'KES'
        result = {
            'total':     round(total, 2),
            'currency':  currency,
            'breakdown': breakdown,
        }
        _logger.info(
            "[PosOrder][compute_credit_note_amount] "
            "order='%s' | TOTAL credit-note amount=%.2f %s",
            self.name, result['total'], currency,
        )
        return result

    # =========================================================================
    # Gift-card issuance
    # =========================================================================

    @api.model
    def create_credit_note_gift_card(self, config_id, amount, partner_id=False, reason='', order_id=False):
        """
        Issue a ``loyalty.card`` (gift card) for the given amount using
        the program configured on the POS terminal.

        The gift card is created with:
          * ``points``  = amount   (1 point == 1 currency unit — standard rule)
          * ``partner_id`` if provided
          * A note in the history linking it to this POS return order

        Parameters
        ----------
        config_id  : int
        amount     : float   — net credit-note amount
        partner_id : int|False
        reason     : str     — free-text reason from the cashier

        Returns
        -------
        dict
            {
                'ok'      : bool,
                'card_id' : int|None,
                'code'    : str|None,
                'amount'  : float,
                'program' : str,
                'error'   : str|None,
            }
        """
        _logger.info(
            "[PosOrder][create_credit_note_gift_card] order_id=%s | "
            "config_id=%s | amount=%.2f | partner_id=%s | reason='%s'",
            order_id, config_id, amount, partner_id, reason,
        )

        if amount <= 0:
            msg = f"Cannot create a gift card for non-positive amount: {amount}"
            _logger.warning(
                "[PosOrder][create_credit_note_gift_card] %s", msg,
            )
            return {'ok': False, 'card_id': None, 'code': None,
                    'amount': amount, 'program': '', 'error': msg}

        config = self.env['pos.config'].browse(config_id)
        ok_program, program_err = config._validate_credit_note_program()
        if not ok_program:
            return {'ok': False, 'card_id': None, 'code': None,
                    'amount': amount, 'program': '', 'error': program_err}

        program = config.credit_note_gift_card_program_id

        # Build loyalty.card vals
        card_vals = {
            'program_id': program.id,
            'points':     amount,
        }
        if partner_id:
            card_vals['partner_id'] = partner_id
        # Link to the source POS return order when its server id is available.
        # When the order hasn't been synced to the server yet (Odoo 18 POS keeps
        # orders as local client records until validation), order_id is False and
        # we simply omit the link — the gift card is still issued correctly.
        if order_id:
            card_vals['source_pos_order_id'] = order_id

        try:
            card = self.env['loyalty.card'].create(card_vals)
            _logger.info(
                "[PosOrder][create_credit_note_gift_card] "
                "Created loyalty.card id=%s code='%s' points=%.2f "
                "for program='%s'",
                card.id, card.code, card.points, program.name,
            )
        except Exception as exc:
            err = f"Failed to create gift card: {exc}"
            _logger.exception(
                "[PosOrder][create_credit_note_gift_card] %s", err,
            )
            return {'ok': False, 'card_id': None, 'code': None,
                    'amount': amount, 'program': program.name, 'error': err}

        # Chatter note on the return order when we have its server id
        if order_id:
            note = (
                f"<p>Credit note gift card issued — Code: <strong>{card.code}</strong>"
                f" | Amount: {amount:.2f} | Program: {program.name}"
            )
            if reason:
                note += f" | Reason: {reason}"
            note += "</p>"
            try:
                order = self.env['pos.order'].browse(order_id)
                if order.exists():
                    order.message_post(
                        body=note, message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
            except Exception:
                _logger.info(
                    "[PosOrder][create_credit_note_gift_card] "
                    "Chatter note skipped. card='%s' amount=%.2f",
                    card.code, amount,
                )

        return {
            'ok':      True,
            'card_id': card.id,
            'code':    card.code,
            'amount':  amount,
            'program': program.name,
            'error':   None,
        }

    # =========================================================================
    # Original order info (advisory summary for the JS breakdown popup)
    # =========================================================================

    @api.model
    def get_original_order_info(self, original_order_id):
        """
        Return a summary of discount and commission data from the
        original sale order so the cashier can review them before
        confirming the credit note.

        Parameters
        ----------
        original_order_id : int

        Returns
        -------
        dict
            {
                'name'             : str,
                'amount_total'     : float,
                'has_discount'     : bool,
                'total_discount'   : float,
                'has_commission'   : bool,
                'total_extra'      : float,
                'total_base_profit': float,
                'extra_state'      : str,
                'profit_state'     : str,
                'lines'            : [
                    {
                        'product'  : str,
                        'qty'      : float,
                        'price'    : float,
                        'discount' : float,
                    }
                ],
            }
        """
        _logger.debug(
            "[PosOrder][get_original_order_info] original_order_id=%s",
            original_order_id,
        )
        order = self.env['pos.order'].browse(original_order_id)
        if not order.exists():
            _logger.warning(
                "[PosOrder][get_original_order_info] order_id=%s not found",
                original_order_id,
            )
            return {}

        # Discount summary
        total_discount = sum(
            (l.price_unit * l.qty * (l.discount / 100.0))
            for l in order.lines
            if l.discount
        )
        has_discount = total_discount > 0

        # Commission summary (soft dep)
        has_commission = False
        total_extra = 0.0
        total_base_profit = 0.0
        extra_state = 'n/a'
        profit_state = 'n/a'

        if hasattr(order, 'total_extra_amount'):
            total_extra = order.total_extra_amount or 0.0
            total_base_profit = getattr(order, 'total_base_profit', 0.0) or 0.0
            extra_state = getattr(order, 'extra_state', 'n/a') or 'n/a'
            profit_state = getattr(order, 'profit_state', 'n/a') or 'n/a'
            has_commission = (total_extra > 0) or (total_base_profit > 0)

        lines = [
            {
                'product':  l.product_id.display_name if l.product_id else '?',
                'qty':      l.qty,
                'price':    l.price_unit,
                'discount': l.discount or 0.0,
            }
            for l in order.lines
        ]

        result = {
            'name':              order.name,
            'amount_total':      order.amount_total,
            'has_discount':      has_discount,
            'total_discount':    total_discount,
            'has_commission':    has_commission,
            'total_extra':       total_extra,
            'total_base_profit': total_base_profit,
            'extra_state':       extra_state,
            'profit_state':      profit_state,
            'lines':             lines,
        }
        _logger.debug(
            "[PosOrder][get_original_order_info] "
            "order='%s' | has_discount=%s | has_commission=%s",
            order.name, has_discount, has_commission,
        )
        return result
