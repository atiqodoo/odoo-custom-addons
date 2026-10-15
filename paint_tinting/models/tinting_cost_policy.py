# -*- coding: utf-8 -*-
from odoo import api, models


class PaintTintingCostPolicy(models.AbstractModel):
    """Central VAT/cost helpers for paint tinting operational records."""

    _name = 'paint.tinting.cost.policy'
    _description = 'Paint Tinting Cost Policy'

    @api.model
    def _get_default_vat_percent(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'paint_tinting.default_vat_percent', '16.0'
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return 16.0

    @api.model
    def _get_vat_factor(self, percent=False):
        vat_percent = self._get_default_vat_percent() if percent is False else percent
        return 1.0 + (vat_percent / 100.0)

    @api.model
    def normalize_amounts(self, amount, amount_is_vat_inclusive=False, vat_percent=False):
        """Return {'excl': x, 'incl': y, 'vat': z} for a monetary amount."""
        amount = amount or 0.0
        factor = self._get_vat_factor(vat_percent)
        if amount_is_vat_inclusive:
            excl = amount / factor if factor else amount
            incl = amount
        else:
            excl = amount
            incl = amount * factor
        return {
            'excl': excl,
            'incl': incl,
            'vat': incl - excl,
        }

    @api.model
    def product_cost_amounts(self, product, quantity=1.0, uom=False, amount_is_vat_inclusive=False, vat_percent=False):
        """Return VAT-aware cost amounts for a product quantity."""
        if not product:
            return {'excl': 0.0, 'incl': 0.0, 'vat': 0.0}

        qty = quantity or 0.0
        product_uom = product.uom_id
        if uom and product_uom and uom != product_uom:
            qty = uom._compute_quantity(qty, product_uom, round=False)

        amount = (product.standard_price or 0.0) * qty
        return self.normalize_amounts(
            amount,
            amount_is_vat_inclusive=amount_is_vat_inclusive,
            vat_percent=vat_percent,
        )
