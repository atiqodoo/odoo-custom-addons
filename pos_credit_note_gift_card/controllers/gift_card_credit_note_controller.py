# -*- coding: utf-8 -*-
"""
gift_card_credit_note_controller.py — HTTP controller
======================================================
Provides JSON-RPC endpoints consumed by the POS JS layer.  All
endpoints return a top-level ``{ok, payload, error}`` envelope so
the JS can handle success and failure uniformly.

Endpoints
---------
/pos/credit_note/validate_return
    POST  — pre-flight check before the cashier clicks Credit Note.
    Verifies non-returnable products, gift-card program health, etc.

/pos/credit_note/compute_amount
    POST  — compute the net gift-card amount for a return order,
    applying discount-distribution and commission-netting per config.

/pos/credit_note/issue
    POST  — create the loyalty.card (gift card) and return its details
    ready for the POS payment screen to apply as a payment line.

/pos/credit_note/original_order_info
    POST  — fetch discount + commission summary of the original sale
    order so the cashier can review it before confirming.

/pos/credit_note/print_receipt_data
    POST  — return all data needed to render and print the thermal
    credit-note receipt (gift card code, amount, lines, header, etc.).

Security
--------
All routes require the caller to be authenticated (``auth='user'``).
The order/config IDs are validated against the active POS session to
prevent cross-session tampering.

Logging
-------
Logger : ``pos_credit_note_gift_card.controller``
Level  : DEBUG for request/response bodies, INFO for business events,
         WARNING/ERROR for failures.
"""

import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger('pos_credit_note_gift_card.controller')


class GiftCardCreditNoteController(http.Controller):
    """
    Central controller for all gift-card credit-note operations.

    All methods share the same validation helpers defined at the bottom
    of this class to keep endpoint handlers thin.
    """

    # =========================================================================
    # Endpoint: validate_return
    # =========================================================================

    @http.route(
        '/pos/credit_note/validate_return',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def validate_return(self, order_id, config_id, **kwargs):
        """
        Pre-flight validation before issuing a credit note.

        Request body
        ------------
        order_id  : int   — the POS return order id (negative-qty lines)
        config_id : int

        Response
        --------
        {
            'ok'        : bool,
            'errors'    : [str],
            'warnings'  : [str],
            'lines_info': [{product, qty, returnable}],
        }
        """
        _logger.info(
            "[Controller][validate_return] order_id=%s config_id=%s",
            order_id, config_id,
        )
        order, error = self._get_order(order_id, config_id)
        if error:
            return self._error_response(error)

        try:
            result = order.validate_return_for_credit_note(config_id)
            _logger.debug(
                "[Controller][validate_return] result=%s", result,
            )
            return self._ok_response(result)
        except Exception as exc:
            _logger.exception(
                "[Controller][validate_return] Unexpected error: %s", exc,
            )
            return self._error_response(str(exc))

    # =========================================================================
    # Endpoint: compute_amount
    # =========================================================================

    @http.route(
        '/pos/credit_note/compute_amount',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def compute_amount(self, order_id, config_id, **kwargs):
        """
        Compute the net gift-card amount for a return order.

        Request body
        ------------
        order_id  : int
        config_id : int

        Response payload
        ----------------
        {
            'total'    : float,
            'currency' : str,
            'breakdown': [{product, gross, discount_adj, commission_adj, net}],
        }
        """
        _logger.info(
            "[Controller][compute_amount] order_id=%s config_id=%s",
            order_id, config_id,
        )
        order, error = self._get_order(order_id, config_id)
        if error:
            return self._error_response(error)

        try:
            result = order.compute_credit_note_amount(config_id)
            _logger.debug(
                "[Controller][compute_amount] total=%.2f breakdown_count=%d",
                result.get('total', 0), len(result.get('breakdown', [])),
            )
            return self._ok_response(result)
        except Exception as exc:
            _logger.exception(
                "[Controller][compute_amount] Unexpected error: %s", exc,
            )
            return self._error_response(str(exc))

    # =========================================================================
    # Endpoint: issue
    # =========================================================================

    @http.route(
        '/pos/credit_note/issue',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def issue_credit_note(
        self, config_id, amount,
        order_id=False, partner_id=False, reason='', **kwargs
    ):
        """
        Create the gift card and return its details.

        Request body
        ------------
        order_id   : int
        config_id  : int
        amount     : float   — net gift-card amount (pre-computed by compute_amount)
        partner_id : int|False
        reason     : str     — cashier's return reason

        Response payload
        ----------------
        {
            'card_id' : int,
            'code'    : str,
            'amount'  : float,
            'program' : str,
        }
        """
        _logger.info(
            "[Controller][issue_credit_note] order_id=%s config_id=%s "
            "amount=%.2f partner_id=%s reason='%s'",
            order_id, config_id, amount, partner_id, reason,
        )

        try:
            result = request.env['pos.order'].create_credit_note_gift_card(
                config_id=config_id,
                amount=amount,
                partner_id=partner_id or False,
                reason=reason,
                order_id=order_id or False,
            )
            if not result.get('ok'):
                return self._error_response(result.get('error', 'Unknown error'))
            _logger.info(
                "[Controller][issue_credit_note] Gift card created: "
                "card_id=%s code='%s' amount=%.2f program='%s'",
                result['card_id'], result['code'],
                result['amount'], result['program'],
            )
            return self._ok_response({
                'card_id': result['card_id'],
                'code':    result['code'],
                'amount':  result['amount'],
                'program': result['program'],
            })
        except Exception as exc:
            _logger.exception(
                "[Controller][issue_credit_note] Unexpected error: %s", exc,
            )
            return self._error_response(str(exc))

    # =========================================================================
    # Endpoint: original_order_info
    # =========================================================================

    @http.route(
        '/pos/credit_note/original_order_info',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def original_order_info(self, original_order_id, **kwargs):
        """
        Return discount/commission summary of the original sale order.

        Request body
        ------------
        original_order_id : int

        Response payload
        ----------------
        See PosOrder.get_original_order_info() docstring.
        """
        _logger.info(
            "[Controller][original_order_info] original_order_id=%s",
            original_order_id,
        )
        try:
            info = request.env['pos.order'].get_original_order_info(
                original_order_id
            )
            return self._ok_response(info)
        except Exception as exc:
            _logger.exception(
                "[Controller][original_order_info] Unexpected error: %s", exc,
            )
            return self._error_response(str(exc))

    # =========================================================================
    # Endpoint: print_receipt_data
    # =========================================================================

    @http.route(
        '/pos/credit_note/print_receipt_data',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def print_receipt_data(self, order_id, card_id, config_id, **kwargs):
        """
        Assemble all data needed by the OWL credit-note receipt component.

        The receipt mirrors a normal POS receipt in format but adds:
          * Gift card code (barcode text)
          * Gift card balance
          * "CREDIT NOTE" header stamp

        Request body
        ------------
        order_id  : int   — the return order
        card_id   : int   — the issued loyalty.card
        config_id : int

        Response payload
        ----------------
        {
            'company_name'    : str,
            'company_address' : str,
            'pos_name'        : str,
            'order_name'      : str,
            'date'            : str,
            'cashier'         : str,
            'lines'           : [{product, qty, unit_price, subtotal}],
            'amount_total'    : float,
            'currency_symbol' : str,
            'gift_card_code'  : str,
            'gift_card_amount': float,
            'gift_card_program': str,
            'reason'          : str,
        }
        """
        _logger.info(
            "[Controller][print_receipt_data] order_id=%s card_id=%s "
            "config_id=%s",
            order_id, card_id, config_id,
        )
        order, error = self._get_order(order_id, config_id)
        if error:
            return self._error_response(error)

        card = request.env['loyalty.card'].browse(card_id)
        if not card.exists():
            return self._error_response(
                f"Gift card (id={card_id}) not found."
            )

        config = request.env['pos.config'].browse(config_id)
        company = config.company_id or request.env.company
        session = order.session_id

        lines = [
            {
                'product':    l.product_id.display_name if l.product_id else '?',
                'qty':        abs(l.qty),
                'unit_price': l.price_unit,
                'discount':   l.discount or 0.0,
                'subtotal':   abs(l.price_subtotal_incl or 0.0),
            }
            for l in order.lines
        ]

        address_parts = filter(None, [
            company.street, company.street2,
            company.city, company.state_id.name if company.state_id else '',
            company.country_id.name if company.country_id else '',
        ])

        data = {
            'company_name':     company.name,
            'company_address':  ', '.join(address_parts),
            'company_phone':    company.phone or '',
            'pos_name':         config.name,
            'order_name':       order.name,
            'date':             order.date_order.strftime('%Y-%m-%d %H:%M') if order.date_order else '',
            'cashier':          session.user_id.name if session else '',
            'lines':            lines,
            'amount_total':     abs(order.amount_total or 0.0),
            'currency_symbol':  order.currency_id.symbol if order.currency_id else '',
            'gift_card_code':   card.code or '',
            'gift_card_amount': card.points or 0.0,
            'gift_card_program': card.program_id.name if card.program_id else '',
        }
        _logger.debug(
            "[Controller][print_receipt_data] data assembled for order='%s' "
            "card='%s'", order.name, card.code,
        )
        return self._ok_response(data)

    # =========================================================================
    # Endpoint: line_commission
    # =========================================================================

    @http.route(
        '/pos/credit_note/line_commission',
        type='json',
        auth='user',
        methods=['POST'],
    )
    def get_line_commission(self, line_ids, **kwargs):
        """
        Return commission fields for the given ORIGINAL-SALE order line IDs.

        The return-order lines always have total_extra_amount / total_base_profit
        zeroed by pos_extra_amount_manager_extended (returns are not revenue
        events).  This endpoint reads the values from the ORIGINAL lines so the
        JS credit-note computation can apply the correct deduction.

        Request body
        ------------
        line_ids : list[int]   — IDs of original (forward-sale) pos.order.line

        Response payload
        ----------------
        { "123": { total_extra_amount: float, total_base_profit: float, qty: float },
          ...  }
        """
        _logger.info(
            "[Controller][get_line_commission] line_ids=%s", line_ids,
        )
        if not line_ids or not isinstance(line_ids, list):
            return self._ok_response({})
        try:
            # Sanitise: accept only integers
            clean_ids = [int(lid) for lid in line_ids if lid]
        except (TypeError, ValueError) as exc:
            return self._error_response(f"Invalid line_ids: {exc}")

        try:
            from ..models.pos_order_line import PosOrderLine as _Model
            data = _Model.get_credit_note_commission(request.env, clean_ids)
            _logger.debug(
                "[Controller][get_line_commission] returning %d entries", len(data),
            )
            return self._ok_response(data)
        except Exception as exc:
            _logger.exception(
                "[Controller][get_line_commission] Unexpected error: %s", exc,
            )
            return self._error_response(str(exc))

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _get_order(self, order_id, config_id):
        """
        Fetch and validate the POS order.

        Returns (order, None) on success or (None, error_message) on failure.
        """
        try:
            order_id = int(order_id)
            config_id = int(config_id)
        except (TypeError, ValueError) as exc:
            msg = f"Invalid order_id or config_id: {exc}"
            _logger.warning("[Controller][_get_order] %s", msg)
            return None, msg

        order = request.env['pos.order'].browse(order_id)
        if not order.exists():
            msg = f"POS order (id={order_id}) not found."
            _logger.warning("[Controller][_get_order] %s", msg)
            return None, msg

        _logger.debug(
            "[Controller][_get_order] Resolved order='%s' (id=%s)",
            order.name, order.id,
        )
        return order, None

    @staticmethod
    def _ok_response(payload):
        return {'ok': True, 'payload': payload, 'error': None}

    @staticmethod
    def _error_response(message):
        _logger.warning("[Controller][_error_response] %s", message)
        return {'ok': False, 'payload': None, 'error': message}
