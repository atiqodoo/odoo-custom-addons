# -*- coding: utf-8 -*-
import logging
import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


_logger = logging.getLogger(__name__)


class SaleOrderTintedStockGuard(models.Model):
    """Require finished, unreserved tinted stock before SO confirmation."""

    _inherit = 'sale.order'

    has_tinted_stock_shortage = fields.Boolean(
        string='Has Tinted Stock Shortage',
        compute='_compute_tinted_stock_shortage_status',
    )
    tinted_stock_shortage_product_count = fields.Integer(
        string='Tinted Products Missing Stock',
        compute='_compute_tinted_stock_shortage_status',
    )

    @api.depends(
        'warehouse_id',
        'order_line.product_id',
        'order_line.product_uom',
        'order_line.product_uom_qty',
        'order_line.tinted_product_created',
    )
    def _compute_tinted_stock_shortage_status(self):
        for order in self:
            if not order.warehouse_id:
                order.has_tinted_stock_shortage = False
                order.tinted_stock_shortage_product_count = 0
                continue
            shortages = order._get_tinted_stock_shortages()
            order.has_tinted_stock_shortage = bool(shortages)
            order.tinted_stock_shortage_product_count = len(shortages)

    def _get_tinted_stock_guard_lines(self):
        """Return processed tinted lines that require physical stock."""
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: (
                not line.display_type
                and line.product_id
                and line.product_uom_qty > 0
                and line.tinted_product_created
                and line.product_id.product_tmpl_id.is_tinted_product
            )
        )

    def _get_tinted_stock_snapshot(self):
        """Return one live warehouse snapshot per tinted product.

        Quantities use the product inventory UoM. Grouping duplicate product
        lines prevents the same available units from being counted twice.
        """
        self.ensure_one()
        warehouse = self.warehouse_id
        if not warehouse or not warehouse.lot_stock_id:
            raise UserError(_(
                "Cannot check tinted product stock because no warehouse stock "
                "location is configured on sales order %s."
            ) % self.display_name)

        grouped = {}
        for line in self._get_tinted_stock_guard_lines():
            product = line.product_id
            requested_qty = line.product_uom._compute_quantity(
                line.product_uom_qty, product.uom_id, round=False,
            )
            values = grouped.setdefault(product.id, {
                'product': product,
                'lines': self.env['sale.order.line'],
                'requested_qty': 0.0,
            })
            values['lines'] |= line
            values['requested_qty'] += requested_qty

        Quant = self.env['stock.quant']
        snapshot = []
        for values in grouped.values():
            product = values['product']
            available_qty = Quant._get_available_quantity(
                product,
                warehouse.lot_stock_id,
                strict=False,
                allow_negative=False,
            )
            requested_qty = values['requested_qty']
            shortage_qty = max(requested_qty - available_qty, 0.0)
            values.update({
                'warehouse': warehouse,
                'available_qty': available_qty,
                'shortage_qty': shortage_qty,
            })
            snapshot.append(values)
            _logger.debug(
                "TINT_STOCK_SNAPSHOT order_id=%s order=%s warehouse_id=%s "
                "location_id=%s product_id=%s line_ids=%s requested=%s "
                "available=%s shortage=%s uom_id=%s user_id=%s",
                self.id, self.name, warehouse.id, warehouse.lot_stock_id.id,
                product.id, values['lines'].ids, requested_qty,
                available_qty, shortage_qty, product.uom_id.id,
                self.env.user.id,
            )
        return snapshot

    def _get_tinted_stock_shortages(self):
        """Extension hook returning products whose stock is insufficient."""
        self.ensure_one()
        return [
            values for values in self._get_tinted_stock_snapshot()
            if float_compare(
                values['available_qty'],
                values['requested_qty'],
                precision_rounding=values['product'].uom_id.rounding,
            ) < 0
        ]

    def _validate_tinted_stock_for_confirmation(self):
        """Block confirmation until all tinted quantities physically exist."""
        self.ensure_one()
        _logger.info(
            "TINT_STOCK_CONFIRM_CHECK_START order_id=%s order=%s warehouse_id=%s "
            "user_id=%s",
            self.id, self.name, self.warehouse_id.id, self.env.user.id,
        )
        shortages = self._get_tinted_stock_shortages()
        if not shortages:
            _logger.info(
                "TINT_STOCK_CONFIRM_CHECK_PASS order_id=%s order=%s user_id=%s",
                self.id, self.name, self.env.user.id,
            )
            return

        details = []
        for values in shortages:
            product = values['product']
            details.append(_(
                "%(product)s: quoted %(requested).2f %(uom)s, available "
                "%(available).2f %(uom)s, missing %(missing).2f %(uom)s",
                product=product.display_name,
                requested=values['requested_qty'],
                available=values['available_qty'],
                missing=values['shortage_qty'],
                uom=product.uom_id.name,
            ))
            _logger.warning(
                "TINT_STOCK_CONFIRM_BLOCKED order_id=%s order=%s warehouse_id=%s "
                "product_id=%s line_ids=%s requested=%s available=%s "
                "shortage=%s uom_id=%s user_id=%s",
                self.id, self.name, values['warehouse'].id, product.id,
                values['lines'].ids, values['requested_qty'],
                values['available_qty'], values['shortage_qty'],
                product.uom_id.id, self.env.user.id,
            )

        raise UserError(_(
            "You cannot confirm this sales order because finished tinted stock "
            "is below the quoted quantity.\n\n%(details)s\n\nUse 'Produce "
            "Missing Qty' on the affected order line, complete production, "
            "then confirm again.",
            details='\n'.join(details),
        ))

    def action_confirm(self):
        for order in self:
            order._validate_tinted_stock_for_confirmation()
        return super().action_confirm()

    def action_produce_next_missing_tinted_qty(self):
        """Header shortcut to the first product currently missing stock."""
        self.ensure_one()
        shortages = self._get_tinted_stock_shortages()
        if not shortages:
            raise UserError(_(
                "No additional tinted production is required. Refresh the "
                "order and confirm it again."
            ))
        shortage = shortages[0]
        source_line = shortage['lines'][-1]
        _logger.info(
            "TINT_STOCK_HEADER_ACTION order_id=%s product_id=%s line_id=%s "
            "shortage=%s user_id=%s",
            self.id, shortage['product'].id, source_line.id,
            shortage['shortage_qty'], self.env.user.id,
        )
        return source_line.action_produce_missing_tinted_qty()


class SaleOrderLineTintedStockGuard(models.Model):
    """Expose live tinted availability and launch shortage production."""

    _inherit = 'sale.order.line'

    tinted_stock_available_qty = fields.Float(
        string='Tinted Available',
        compute='_compute_tinted_stock_status',
        digits='Product Unit of Measure',
        help='Current unreserved finished quantity in the sales order warehouse.',
    )
    tinted_stock_shortage_qty = fields.Float(
        string='Tinted Missing',
        compute='_compute_tinted_stock_status',
        digits='Product Unit of Measure',
        help='Additional finished quantity required before this order can be confirmed.',
    )

    @api.depends(
        'order_id.warehouse_id',
        'order_id.order_line.product_id',
        'order_id.order_line.product_uom',
        'order_id.order_line.product_uom_qty',
        'order_id.order_line.tinted_product_created',
    )
    def _compute_tinted_stock_status(self):
        self.tinted_stock_available_qty = 0.0
        self.tinted_stock_shortage_qty = 0.0
        for order in self.mapped('order_id'):
            if not order.warehouse_id:
                continue
            for values in order._get_tinted_stock_snapshot():
                remaining = values['available_qty']
                product = values['product']
                for line in values['lines'].sorted('id'):
                    requested = line.product_uom._compute_quantity(
                        line.product_uom_qty, product.uom_id, round=False,
                    )
                    allocated = min(max(remaining, 0.0), requested)
                    shortage = max(requested - allocated, 0.0)
                    line.tinted_stock_available_qty = product.uom_id._compute_quantity(
                        allocated, line.product_uom, round=False,
                    )
                    line.tinted_stock_shortage_qty = product.uom_id._compute_quantity(
                        shortage, line.product_uom, round=False,
                    )
                    remaining -= allocated

    def action_produce_missing_tinted_qty(self):
        """Open the existing duplicate-MO wizard prefilled from live shortage."""
        self.ensure_one()
        order = self.order_id
        product = self.product_id
        if not (
            self.tinted_product_created
            and product
            and product.product_tmpl_id.is_tinted_product
        ):
            raise UserError(_(
                "Create the tinted product and its first Manufacturing Order "
                "before producing the missing quantity."
            ))

        product_snapshot = next(
            (
                values for values in order._get_tinted_stock_snapshot()
                if values['product'] == product
            ),
            None,
        )
        shortage = product_snapshot['shortage_qty'] if product_snapshot else 0.0
        if float_compare(
            shortage, 0.0, precision_rounding=product.uom_id.rounding,
        ) <= 0:
            _logger.info(
                "TINT_STOCK_DUPLICATE_NOT_NEEDED order_id=%s line_id=%s "
                "product_id=%s user_id=%s",
                order.id, self.id, product.id, self.env.user.id,
            )
            raise UserError(_(
                "No additional production is required. Refresh the order and "
                "confirm it again."
            ))

        source_mo = self.env['mrp.production'].search([
            ('product_id', '=', product.id),
            ('is_tinting_mo', '=', True),
            ('state', '!=', 'cancel'),
        ], order='id desc', limit=1)
        if not source_mo:
            _logger.error(
                "TINT_STOCK_SOURCE_MO_MISSING order_id=%s line_id=%s "
                "product_id=%s shortage=%s user_id=%s",
                order.id, self.id, product.id, shortage, self.env.user.id,
            )
            raise UserError(_(
                "No usable tinting Manufacturing Order was found for %s."
            ) % product.display_name)

        output_per_mo = source_mo.product_uom_id._compute_quantity(
            source_mo.product_qty, product.uom_id, round=False,
        )
        if float_compare(
            output_per_mo, 0.0, precision_rounding=product.uom_id.rounding,
        ) <= 0:
            raise UserError(_(
                "The source Manufacturing Order has an invalid output quantity."
            ))
        duplicate_count = max(
            1, int(math.ceil((shortage / output_per_mo) - 1e-9)),
        )

        _logger.info(
            "TINT_STOCK_DUPLICATE_WIZARD_OPEN order_id=%s line_id=%s "
            "product_id=%s source_mo_id=%s requested=%s available=%s "
            "shortage=%s output_per_mo=%s duplicate_count=%s user_id=%s",
            order.id, self.id, product.id, source_mo.id,
            product_snapshot['requested_qty'], product_snapshot['available_qty'],
            shortage, output_per_mo, duplicate_count, self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Produce Missing Tinted Quantity'),
            'res_model': 'mrp.production.duplicate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_source_mo_id': source_mo.id,
                'default_product_name': product.display_name,
                'default_quantity': duplicate_count,
                'default_auto_confirm': True,
                'default_selling_price': self.price_unit,
                'default_source_sale_order_id': order.id,
                'default_source_sale_order_line_id': self.id,
            },
        }
