# -*- coding: utf-8 -*-
"""Version selection and application in the operational tinting wizard."""

import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class TintWizardFormulaVersionSelection(models.TransientModel):
    _inherit = 'tint.wizard'

    formula_version_id = fields.Many2one(
        'tinting.formula.version', string='Formula Version', readonly=False,
        domain="[('id', 'in', available_formula_version_ids)]",
        help='Approved or superseded version selected for this tint.',
    )
    available_formula_version_ids = fields.Many2many(
        'tinting.formula.version', compute='_compute_available_formula_versions',
    )
    last_counted_formula_version_id = fields.Many2one(
        'tinting.formula.version', string='Last Counted Formula Version', readonly=True,
    )

    @api.depends('formula_id', 'formula_id.version_ids.state', 'formula_id.version_ids.active')
    def _compute_available_formula_versions(self):
        for wizard in self:
            wizard.available_formula_version_ids = wizard.formula_id.version_ids.filtered(
                lambda version: version.active and version.state in ('approved', 'superseded')
            )

    def _search_and_apply_formula(self):
        self.ensure_one()
        if not self.base_variant_id or not self.colour_code_id:
            return self._clear_formula_shots()
        service = self.env['tinting.formula.recipe.service'].sudo()
        base_category = self.base_variant_id.categ_id
        base_uom = self.base_variant_id.uom_id
        attribute_value = self.base_variant_id.product_template_attribute_value_ids[:1]
        attribute_name = service.normalize_attribute(attribute_value.name if attribute_value else '')
        family = service.find_family(
            self.colour_code_id, base_category, base_uom, attribute_name,
        )
        _logger.info(
            "FORMULA_WIZARD_VERSION_SEARCH wizard_id=%s colour_id=%s category_id=%s "
            "uom_id=%s attribute=%s family_id=%s",
            self.id, self.colour_code_id.id, base_category.id, base_uom.id,
            attribute_name, family.id,
        )
        if not family:
            return self._clear_formula_shots()
        service.ensure_legacy_version(family)
        available = family.version_ids.filtered(
            lambda version: version.active and version.state in ('approved', 'superseded')
        ).sorted(key=lambda version: version.version_number, reverse=True)
        version = family.default_version_id if family.default_version_id in available else available[:1]
        self.formula_id = family
        if not version:
            _logger.warning(
                "FORMULA_WIZARD_NO_APPROVED_VERSION wizard_id=%s family_id=%s version_states=%s",
                self.id, family.id, family.version_ids.mapped('state'),
            )
            self.formula_version_id = False
            self.formula_applied = False
            for line in self.colorant_line_ids:
                line.shots = 0.0
            return {
                'warning': {
                    'title': _('Formula awaiting approval'),
                    'message': _('This formula family has no Approved version available for usage.'),
                }
            }
        return self._apply_formula_version(version)

    def _apply_formula_version(self, version, increment_usage=True):
        self.ensure_one()
        version.ensure_one()
        shots = version.get_shots_dict()
        applied = 0
        for line in self.colorant_line_ids:
            value = shots.get(line.colorant_code, 0.0)
            line.shots = value
            applied += bool(value)
        self.formula_id = version.formula_id
        self.formula_version_id = version
        self.formula_applied = True
        self.selling_price_manually_set = False
        should_increment = increment_usage and self.last_counted_formula_version_id != version
        if should_increment:
            version.increment_usage_counter()
            version.formula_id.increment_usage_counter()
            self.last_counted_formula_version_id = version
        _logger.info(
            "FORMULA_WIZARD_VERSION_APPLIED wizard_id=%s family_id=%s version_id=%s "
            "version_number=%s colorants=%s increment_usage=%s user_id=%s",
            self.id, version.formula_id.id, version.id, version.version_number,
            applied, should_increment, self.env.user.id,
        )
        return {
            'warning': {
                'title': _('Formula Version Applied'),
                'message': _('%(version)s loaded with %(count)s colorants. You may adjust shots before creating the MO.',
                             version=version.display_name, count=applied),
            }
        }

    @api.onchange('formula_version_id')
    def _onchange_formula_version_id(self):
        if self.formula_version_id and self.formula_version_id.formula_id == self.formula_id:
            return self._apply_formula_version(self.formula_version_id)

    def _clear_formula_shots(self):
        result = super()._clear_formula_shots()
        self.formula_version_id = False
        self.last_counted_formula_version_id = False
        return result
