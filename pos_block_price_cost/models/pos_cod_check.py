# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class PosSessionCodCheck(models.Model):
    _inherit = 'pos.session'

    def validate_cod_below_cost(self, lines_data):
        """
        Returns order lines whose selling price (incl. VAT) is below their cost
        (incl. VAT). Called via ORM RPC from cod_check.js when the cashier
        clicks the COD dispatch button on the Product Screen.

        Args:
            lines_data: list of dicts —
                product_id    (int)
                price_incl    (float)  effective selling price already inclusive of VAT
                              (priceWithTax from POS get_all_prices)
                tax_ids       (list[int])  taxes applied on the line

        Returns:
            list of dicts —
                product_name  (str)
                cost_incl     (float)  standard_price + applicable taxes
                price_incl    (float)  selling price incl. VAT passed in
        """
        self.ensure_one()
        offenders = []

        for line in lines_data:
            product = self.env['product.product'].browse(line['product_id'])
            cost = product.standard_price or 0.0
            if cost <= 0:
                continue

            price_incl = line.get('price_incl', 0.0)
            taxes = self.env['account.tax'].browse(line.get('tax_ids', []))

            if taxes:
                # handle_price_include=False: standard_price is always ex-VAT,
                # so force taxes to be added on top even when price_include=True.
                cost_result = taxes.compute_all(
                    cost, quantity=1, product=product, handle_price_include=False
                )
                cost_incl = cost_result['total_included']
            else:
                cost_incl = cost

            if price_incl < cost_incl:
                offenders.append({
                    'product_name': product.display_name,
                    'cost_incl': round(cost_incl, 2),
                    'price_incl': round(price_incl, 2),
                })
                _logger.info(
                    "pos_block_price_cost [cod_check]: '%s' below cost — "
                    "price_incl=%.2f  cost_incl=%.2f",
                    product.display_name, price_incl, cost_incl,
                )

        return offenders
