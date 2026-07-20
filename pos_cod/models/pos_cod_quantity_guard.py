# -*- coding: utf-8 -*-
"""New COD dispatch quantity validation.

This model deliberately wraps only POS UI synchronization. COD collection and
return operations use their dedicated RPC methods and never pass this guard.
"""

import logging
import math

from odoo import _, api, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)
_COD_QTY_GUARD = '[COD][QuantityGuard]'


class PosOrderCodQuantityGuard(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _cod_quantity_guard_product_name(self, line_values, line_number):
        product_id = line_values.get('product_id')
        if isinstance(product_id, (list, tuple)):
            product_id = product_id[0] if product_id else False

        product = self.env['product.product'].browse(product_id).exists() if product_id else False
        return product.display_name if product else _('Line %s') % line_number

    @api.model
    def _cod_validate_new_order_quantities(self, order_data):
        """Reject non-positive quantities before COD order creation starts."""
        order_name = order_data.get('name') or order_data.get('uuid') or _('Unnamed order')
        line_commands = order_data.get('lines') or []

        _logger.info(
            '%s validating new COD payload order=%s uuid=%s partner_id=%s lines=%s',
            _COD_QTY_GUARD,
            order_name,
            order_data.get('uuid'),
            order_data.get('partner_id'),
            len(line_commands),
        )

        if not line_commands:
            _logger.warning(
                '%s blocked COD payload with no lines order=%s uuid=%s',
                _COD_QTY_GUARD,
                order_name,
                order_data.get('uuid'),
            )
            raise ValidationError(_('A COD order must contain at least one product line.'))

        invalid_lines = []
        for line_number, command in enumerate(line_commands, start=1):
            line_values = (
                command[2]
                if isinstance(command, (list, tuple))
                and len(command) >= 3
                and isinstance(command[2], dict)
                else {}
            )
            raw_quantity = line_values.get('qty')
            try:
                quantity = float(raw_quantity)
            except (TypeError, ValueError):
                quantity = float('nan')

            product_name = self._cod_quantity_guard_product_name(line_values, line_number)
            is_valid = math.isfinite(quantity) and quantity > 0

            _logger.debug(
                '%s line check order=%s line=%s product_id=%s product=%s '
                'raw_qty=%r parsed_qty=%s price_unit=%s discount=%s valid=%s',
                _COD_QTY_GUARD,
                order_name,
                line_number,
                line_values.get('product_id'),
                product_name,
                raw_quantity,
                quantity,
                line_values.get('price_unit'),
                line_values.get('discount'),
                is_valid,
            )

            if not is_valid:
                invalid_lines.append((product_name, raw_quantity))

        if invalid_lines:
            invalid_summary = ', '.join(
                _('%(product)s (Qty: %(quantity)s)', product=product, quantity=quantity)
                for product, quantity in invalid_lines
            )
            _logger.warning(
                '%s blocked COD payload order=%s uuid=%s invalid_lines=%s',
                _COD_QTY_GUARD,
                order_name,
                order_data.get('uuid'),
                invalid_summary,
            )
            raise ValidationError(
                _(
                    'Every COD item must have a quantity greater than zero. '
                    'Correct or remove: %s',
                    invalid_summary,
                )
            )

        _logger.info(
            '%s COD payload passed order=%s uuid=%s lines=%s',
            _COD_QTY_GUARD,
            order_name,
            order_data.get('uuid'),
            len(line_commands),
        )

    @api.model
    def sync_from_ui(self, orders):
        """Validate only new COD dispatch payloads, then preserve existing flow."""
        for order_data in orders:
            if order_data.get('is_cod'):
                self._cod_validate_new_order_quantities(order_data)
        return super().sync_from_ui(orders)
