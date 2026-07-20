# -*- coding: utf-8 -*-
"""APS-aware tinted product naming without changing product creation logic."""

import logging

from odoo import models


_logger = logging.getLogger(__name__)


class TintWizardApsProductNaming(models.TransientModel):
    _inherit = 'tint.wizard'

    def _get_tinted_product_name(self):
        """Return the existing standard name, extended only for APS versions."""
        self.ensure_one()
        standard_name = (
            f"{self.base_variant_id.display_name} – "
            f"{self.colour_name} [{self.colour_code_id.code}]"
        ).strip()
        version = self.formula_version_id
        decision = self.env.context.get('tint_formula_decision')
        use_aps_name = bool(version and version.is_aps and decision != 'updated')

        if not use_aps_name:
            _logger.info(
                "TINT_PRODUCT_NAME_STANDARD tint_wizard_id=%s formula_version_id=%s "
                "decision=%s product_name=%s",
                self.id, version.id, decision, standard_name,
            )
            return standard_name

        customer = version.aps_customer_id
        aps_name = (
            f"{standard_name} - APS - {customer.display_name} "
            f"- V{version.version_number}"
        )
        _logger.info(
            "TINT_PRODUCT_NAME_APS tint_wizard_id=%s formula_id=%s "
            "formula_version_id=%s customer_id=%s decision=%s product_name=%s",
            self.id, version.formula_id.id, version.id, customer.id,
            decision, aps_name,
        )
        return aps_name
