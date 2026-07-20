# -*- coding: utf-8 -*-
"""Carry APS identity and exact recipe through sale-order product creation."""

import json
import logging

from odoo import _, fields, models


_logger = logging.getLogger(__name__)


class SaleOrderLineApsTinting(models.Model):
    _inherit = 'sale.order.line'

    tinting_formula_version_id = fields.Many2one(
        'tinting.formula.version', string='Tinting Formula Version',
        copy=False, readonly=True, index=True,
        help='Exact formula version selected in the Tinting/Cost Comparison workflow.',
    )
    tinting_formula_is_aps = fields.Boolean(
        related='tinting_formula_version_id.is_aps', string='APS Formula', readonly=True,
    )
    tinting_aps_customer_id = fields.Many2one(
        related='tinting_formula_version_id.aps_customer_id',
        string='APS Customer', readonly=True,
    )

    def _get_tinted_product_name_from_sale(self):
        """Apply the same APS naming convention used by the Tinting Wizard."""
        self.ensure_one()
        standard_name = (
            f"{self.base_product_id.display_name} – "
            f"{self.colour_code_id.name} [{self.colour_code_id.code}]"
        ).strip()
        version = self.tinting_formula_version_id
        if not version or not version.is_aps:
            _logger.info(
                "SALE_TINT_PRODUCT_NAME_STANDARD sale_line_id=%s order_id=%s "
                "formula_version_id=%s product_name=%s",
                self.id, self.order_id.id, version.id, standard_name,
            )
            return standard_name

        aps_name = (
            f"{standard_name} - APS - {version.aps_customer_id.display_name} "
            f"- V{version.version_number}"
        )
        _logger.info(
            "SALE_TINT_PRODUCT_NAME_APS sale_line_id=%s order_id=%s family_id=%s "
            "formula_version_id=%s customer_id=%s product_name=%s",
            self.id, self.order_id.id, version.formula_id.id, version.id,
            version.aps_customer_id.id, aps_name,
        )
        return aps_name

    def _prepare_sale_recipe_override(self, exists_wizard):
        """Forward the quoted recipe if an APS product already exists."""
        self.ensure_one()
        if not self.tinting_formula_version_id.is_aps or not exists_wizard.mo_id.bom_id:
            return False
        try:
            raw_recipe = json.loads(self.tinting_formula_json or '{}')
        except (TypeError, ValueError):
            _logger.exception(
                "SALE_APS_RECIPE_JSON_INVALID sale_line_id=%s payload=%s",
                self.id, self.tinting_formula_json,
            )
            return False

        service = self.env['tinting.formula.recipe.service']
        requested_recipe = {
            code: data.get('shots', 0.0)
            for code, data in raw_recipe.items()
            if isinstance(data, dict)
        }
        source_recipe, _products = service.recipe_from_bom(exists_wizard.mo_id.bom_id)
        changed = service.signature(requested_recipe) != service.signature(source_recipe)
        if not changed:
            _logger.info(
                "SALE_APS_EXISTING_RECIPE_MATCH sale_line_id=%s exists_wizard_id=%s "
                "version_id=%s recipe=%s",
                self.id, exists_wizard.id, self.tinting_formula_version_id.id,
                requested_recipe,
            )
            return False

        changes = service.diff(source_recipe, requested_recipe)
        summary = []
        for change in changes:
            if change['type'] == 'added':
                summary.append(_('%(code)s added: %(new).2f shots', **change))
            elif change['type'] == 'removed':
                summary.append(_('%(code)s removed: %(old).2f shots', **change))
            else:
                summary.append(_(
                    '%(code)s changed: %(old).2f -> %(new).2f shots', **change,
                ))

        payload = {}
        for code, shots in requested_recipe.items():
            product = self.env['product.product'].search([
                ('product_tmpl_id.is_colorant', '=', True),
                ('product_tmpl_id.colorant_code', '=ilike', code),
            ], limit=1)
            if product and shots > 0:
                payload[code] = {'colorant_id': product.id, 'shots': shots}

        exists_wizard.write({
            'recipe_override_json': json.dumps(payload, sort_keys=True),
            'has_recipe_override': True,
            'recipe_change_summary': '\n'.join(summary),
        })
        _logger.warning(
            "SALE_APS_EXISTING_RECIPE_OVERRIDE sale_line_id=%s exists_wizard_id=%s "
            "source_mo_id=%s version_id=%s source_recipe=%s requested_recipe=%s changes=%s",
            self.id, exists_wizard.id, exists_wizard.mo_id.id,
            self.tinting_formula_version_id.id, source_recipe, requested_recipe, changes,
        )
        return True

    def action_create_tinted_product_for_line(self):
        self.ensure_one()
        _logger.info(
            "SALE_APS_TINT_CREATE_START sale_line_id=%s order_id=%s version_id=%s "
            "is_aps=%s customer_id=%s formula_json=%s",
            self.id, self.order_id.id, self.tinting_formula_version_id.id,
            self.tinting_formula_version_id.is_aps,
            self.tinting_formula_version_id.aps_customer_id.id,
            self.tinting_formula_json,
        )
        result = super().action_create_tinted_product_for_line()
        if isinstance(result, dict) and result.get('res_model') == 'tint.product.exists.wizard':
            exists_wizard = self.env['tint.product.exists.wizard'].browse(
                result.get('res_id')
            ).exists()
            if exists_wizard:
                self._prepare_sale_recipe_override(exists_wizard)
        _logger.info(
            "SALE_APS_TINT_CREATE_RESULT sale_line_id=%s version_id=%s result_model=%s "
            "result_res_id=%s",
            self.id, self.tinting_formula_version_id.id,
            result.get('res_model') if isinstance(result, dict) else False,
            result.get('res_id') if isinstance(result, dict) else False,
        )
        return result
