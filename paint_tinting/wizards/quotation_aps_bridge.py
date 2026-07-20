# -*- coding: utf-8 -*-
"""Propagate selected APS formula identity from comparison into sale lines."""

import json
import logging

from odoo import models


_logger = logging.getLogger(__name__)


class QuotationGeneratorApsBridge(models.TransientModel):
    _inherit = 'quotation.generator.wizard'

    def action_generate_quotation(self):
        self.ensure_one()
        source = self.source_wizard_id
        parent = source.parent_wizard_id
        version = parent.formula_version_id
        formula_json = (
            source.scaled_colorant_shots_json
            if source.show_scaled_products and source.scaled_colorant_shots_json
            else source.colorant_shots_json
        ) or '{}'
        try:
            raw_recipe = json.loads(formula_json)
            quoted_recipe = {
                code: data.get('shots', 0.0)
                for code, data in raw_recipe.items()
                if isinstance(data, dict)
            }
        except (TypeError, ValueError):
            quoted_recipe = {}
            _logger.exception(
                "QUOTATION_APS_FORMULA_JSON_INVALID quotation_wizard_id=%s "
                "source_wizard_id=%s payload=%s",
                self.id, source.id, formula_json,
            )

        service = self.env['tinting.formula.recipe.service']
        quoted_signature = service.signature(quoted_recipe) if quoted_recipe else False
        _logger.info(
            "QUOTATION_APS_BRIDGE quotation_wizard_id=%s source_wizard_id=%s "
            "parent_tint_wizard_id=%s version_id=%s is_aps=%s aps_customer_id=%s "
            "version_signature=%s quoted_signature=%s scaled=%s quoted_recipe=%s",
            self.id, source.id, parent.id, version.id, version.is_aps,
            version.aps_customer_id.id, version.recipe_signature,
            quoted_signature, source.show_scaled_products, quoted_recipe,
        )
        return super(
            QuotationGeneratorApsBridge,
            self.with_context(default_tinting_formula_version_id=version.id or False),
        ).action_generate_quotation()
