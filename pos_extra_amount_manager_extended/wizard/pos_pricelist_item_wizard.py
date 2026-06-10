# -*- coding: utf-8 -*-
"""
Wizard: add a missing product to the POS order pricelist after sale.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosPricelistItemWizard(models.TransientModel):
    _name = 'pos.pricelist.item.wizard'
    _description = 'Add POS Product to Pricelist Wizard'

    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        required=True,
        readonly=True,
    )
    pos_order_id = fields.Many2one(
        related='pos_order_line_id.order_id',
        string='POS Order',
        readonly=True,
    )
    product_id = fields.Many2one(
        related='pos_order_line_id.product_id',
        string='Product',
        readonly=True,
    )
    pricelist_id = fields.Many2one(
        related='pos_order_line_id.order_id.pricelist_id',
        string='Pricelist',
        readonly=True,
    )
    paid_price_per_unit = fields.Monetary(
        string='Paid Price Per Unit',
        compute='_compute_amounts',
        currency_field='currency_id',
    )
    current_product_sales_price = fields.Monetary(
        string='Product Sales Price',
        compute='_compute_amounts',
        currency_field='currency_id',
    )
    cost_price_incl_vat = fields.Monetary(
        string='Cost Price Incl. VAT',
        compute='_compute_amounts',
        currency_field='currency_id',
        help="Landed/AVCO cost including VAT. Uses product cost_price_incl_vat when available; otherwise standard_price plus product VAT."
    )
    fixed_price = fields.Float(
        string='Pricelist Price',
        digits='Product Price',
        required=True,
        help="Normal pricelist price to add for this product. Extra amount will be recalculated from this price."
    )
    expected_extra_per_unit = fields.Monetary(
        string='Expected Extra Per Unit',
        compute='_compute_amounts',
        currency_field='currency_id',
    )
    expected_total_extra = fields.Monetary(
        string='Expected Total Extra',
        compute='_compute_amounts',
        currency_field='currency_id',
    )
    apply_on = fields.Selection([
        ('0_product_variant', 'Product Variant'),
        ('1_product', 'Product Template'),
    ], string='Apply On', default='0_product_variant', required=True)
    min_quantity = fields.Float(
        string='Minimum Quantity',
        default=0.0,
        digits='Product Unit of Measure',
    )
    currency_id = fields.Many2one(
        related='pos_order_line_id.currency_id',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='pos_order_line_id.company_id',
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = res.get('pos_order_line_id') or self.env.context.get('default_pos_order_line_id')
        line = self.env['pos.order.line'].browse(line_id).exists()

        _logger.info(
            "[Pricelist Wizard][default_get] fields=%s | context_line=%s | line_exists=%s",
            fields_list,
            line_id,
            bool(line),
        )

        if line:
            paid_price = line.price_subtotal_incl / line.qty if line.qty else 0.0
            default_price = line.product_id.lst_price or paid_price
            res.setdefault('fixed_price', default_price)
            _logger.debug(
                "[Pricelist Wizard][default_get] line_id=%s | product=%s | "
                "paid_price=%.4f | product_lst_price=%.4f | default_fixed_price=%.4f",
                line.id,
                line.product_id.display_name,
                paid_price,
                line.product_id.lst_price or 0.0,
                default_price,
            )

        return res

    @api.depends('pos_order_line_id', 'fixed_price')
    def _compute_amounts(self):
        for wizard in self:
            line = wizard.pos_order_line_id
            if not line or not line.product_id or not line.qty:
                wizard.paid_price_per_unit = 0.0
                wizard.current_product_sales_price = 0.0
                wizard.cost_price_incl_vat = 0.0
                wizard.expected_extra_per_unit = 0.0
                wizard.expected_total_extra = 0.0
                continue

            paid_price = line.price_subtotal_incl / line.qty
            ordered_qty = int(abs(line.qty)) or 1
            effective_qty = min(line.calc_qty or 1, ordered_qty)
            extra_per_unit = paid_price - (wizard.fixed_price or 0.0)

            wizard.paid_price_per_unit = paid_price
            wizard.current_product_sales_price = line.product_id.lst_price
            wizard.cost_price_incl_vat = wizard._get_product_cost_incl_vat(line.product_id)
            wizard.expected_extra_per_unit = extra_per_unit
            wizard.expected_total_extra = extra_per_unit * effective_qty

            _logger.debug(
                "[Pricelist Wizard][_compute_amounts] wizard_id=%s | line_id=%s | "
                "paid=%.4f | sales_price=%.4f | cost_incl_vat=%.4f | "
                "fixed_price=%.4f | effective_qty=%s | "
                "expected_extra_per_unit=%.4f | expected_total_extra=%.4f",
                wizard.id,
                line.id,
                paid_price,
                wizard.current_product_sales_price,
                wizard.cost_price_incl_vat,
                wizard.fixed_price or 0.0,
                effective_qty,
                wizard.expected_extra_per_unit,
                wizard.expected_total_extra,
            )

    def _get_product_cost_incl_vat(self, product):
        """Return landed/AVCO cost including VAT for wizard display."""
        self.ensure_one()
        product.ensure_one()

        template = product.product_tmpl_id
        explicit_cost = getattr(template, 'cost_price_incl_vat', 0.0) or 0.0
        if explicit_cost:
            _logger.debug(
                "[Pricelist Wizard][_get_product_cost_incl_vat] product=%s | "
                "source=cost_price_incl_vat | value=%.4f",
                product.display_name,
                explicit_cost,
            )
            return explicit_cost

        studio_cost = getattr(template, 'x_studio_cost_inclu_1', 0.0) or 0.0
        if studio_cost:
            _logger.debug(
                "[Pricelist Wizard][_get_product_cost_incl_vat] product=%s | "
                "source=x_studio_cost_inclu_1 | value=%.4f",
                product.display_name,
                studio_cost,
            )
            return studio_cost

        taxes = product.taxes_id.filtered(lambda tax: tax.amount_type == 'percent')
        vat_rate = sum(taxes.mapped('amount')) / 100.0 if taxes else 0.0
        fallback_cost = (product.standard_price or 0.0) * (1.0 + vat_rate)

        _logger.warning(
            "[Pricelist Wizard][_get_product_cost_incl_vat] product=%s | "
            "No explicit incl-VAT cost found. Fallback standard_price=%.4f | "
            "vat_rate=%.4f | fallback_cost=%.4f",
            product.display_name,
            product.standard_price or 0.0,
            vat_rate,
            fallback_cost,
        )
        return fallback_cost

    @api.constrains('fixed_price', 'min_quantity')
    def _check_values(self):
        for wizard in self:
            if wizard.fixed_price <= 0:
                raise ValidationError('Pricelist price must be greater than zero.')
            if wizard.min_quantity < 0:
                raise ValidationError('Minimum quantity cannot be negative.')

    def action_add_to_pricelist(self):
        self.ensure_one()
        line = self.pos_order_line_id

        _logger.info(
            "[Pricelist Wizard][action_add_to_pricelist] START | wizard_id=%s | "
            "line_id=%s | order=%s | product=%s | pricelist=%s | "
            "apply_on=%s | fixed_price=%.4f | min_quantity=%.4f",
            self.id,
            line.id if line else None,
            line.order_id.name if line and line.order_id else 'N/A',
            line.product_id.display_name if line and line.product_id else 'N/A',
            line.order_id.pricelist_id.display_name if line and line.order_id.pricelist_id else 'N/A',
            self.apply_on,
            self.fixed_price,
            self.min_quantity,
        )

        if not line:
            raise UserError('The POS order line no longer exists.')
        if not line.product_id:
            raise UserError('The POS order line has no product.')
        if not line.order_id.pricelist_id:
            raise UserError('The POS order has no pricelist.')
        if line.qty and line.qty < 0:
            raise UserError('Refund lines cannot create commission pricelist rules.')

        existing_rule = line.order_id.pricelist_id._pos_extra_find_product_rule(
            line.product_id,
            quantity=1.0,
            date=line.order_id.date_order,
        )
        if existing_rule:
            _logger.warning(
                "[Pricelist Wizard][action_add_to_pricelist] Existing rule detected | "
                "line_id=%s | rule_id=%s. Recompute only.",
                line.id,
                existing_rule.id,
            )
            line._compute_extra_and_profit()
            return self._success_action(line, existing_rule)

        vals = {
            'pricelist_id': line.order_id.pricelist_id.id,
            'applied_on': self.apply_on,
            'compute_price': 'fixed',
            'fixed_price': self.fixed_price,
            'min_quantity': self.min_quantity,
            'pos_added_from_order_line_id': line.id,
        }
        if self.apply_on == '0_product_variant':
            vals['product_id'] = line.product_id.id
            vals['product_tmpl_id'] = line.product_id.product_tmpl_id.id
        else:
            vals['product_tmpl_id'] = line.product_id.product_tmpl_id.id

        _logger.debug("[Pricelist Wizard][action_add_to_pricelist] Creating rule vals=%s", vals)
        rule = self.env['product.pricelist.item'].create(vals)

        _logger.info(
            "[Pricelist Wizard][action_add_to_pricelist] Rule created | "
            "rule_id=%s | pricelist=%s | product=%s | fixed_price=%.4f",
            rule.id,
            rule.pricelist_id.display_name,
            line.product_id.display_name,
            rule.fixed_price,
        )

        line._compute_extra_and_profit()
        line.order_id._compute_totals()

        _logger.info(
            "[Pricelist Wizard][action_add_to_pricelist] COMPLETE | "
            "line_id=%s | rule_id=%s | recalculated_extra=%.4f | "
            "order_total_extra=%.4f",
            line.id,
            rule.id,
            line.total_extra_amount,
            line.order_id.total_extra_amount,
        )
        return self._success_action(line, rule)

    def _success_action(self, line, rule):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pricelist Updated',
                'message': (
                    f'{line.product_id.display_name} added to {rule.pricelist_id.display_name}. '
                    f'Extra amount recalculated.'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
