# -*- coding: utf-8 -*-
"""Allow a first formula to be explicitly created as customer APS."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintWizardNewApsFormula(models.TransientModel):
    _inherit = 'tint.wizard'

    has_saved_formula = fields.Boolean(
        string='Saved Formula Exists', compute='_compute_has_saved_formula',
    )
    new_formula_aps = fields.Boolean(
        string='APS (As Per Sample)', default=False,
        help='Create the first formula as an approved customer-specific APS formula.',
    )
    new_formula_aps_customer_id = fields.Many2one(
        'res.partner', string='APS Customer',
        help='Customer whose sample this first formula matches.',
    )

    @api.depends('base_variant_id', 'colour_code_id')
    def _compute_has_saved_formula(self):
        for wizard in self:
            family = wizard._get_tint_formula_family() if (
                wizard.base_variant_id and wizard.colour_code_id
            ) else False
            has_saved = bool(family and (
                family.sudo().version_ids or family.sudo().formula_line_ids
            ))
            wizard.has_saved_formula = has_saved
            _logger.debug(
                "TINT_NEW_APS_AVAILABILITY tint_wizard_id=%s base_id=%s colour_id=%s "
                "family_id=%s has_saved_formula=%s",
                wizard.id, wizard.base_variant_id.id, wizard.colour_code_id.id,
                family.id if family else False, has_saved,
            )

    @api.onchange('base_variant_id', 'colour_code_id', 'has_saved_formula')
    def _onchange_new_aps_availability(self):
        if self.has_saved_formula:
            if self.new_formula_aps or self.new_formula_aps_customer_id:
                _logger.info(
                    "TINT_NEW_APS_RESET tint_wizard_id=%s reason=saved_formula_found "
                    "family_id=%s",
                    self.id, self._get_tint_formula_family().id,
                )
            self.new_formula_aps = False
            self.new_formula_aps_customer_id = False

    def _prepare_first_aps_formula_family(self):
        self.ensure_one()
        family = self._get_tint_formula_family()
        if family:
            return family
        service = self.env['tinting.formula.recipe.service'].sudo()
        attribute_value = self.base_variant_id.product_template_attribute_value_ids[:1]
        attribute_name = service.normalize_attribute(attribute_value.name if attribute_value else '')
        family = self.env['tinting.formula'].sudo().create({
            'colour_code_id': self.colour_code_id.id,
            'base_category_id': self.base_variant_id.categ_id.id,
            'base_uom_id': self.base_variant_id.uom_id.id,
            'base_attribute_id': attribute_value.id if attribute_value else False,
            'state': 'validated',
            'notes': _('Formula family created from the Tinting Wizard for first APS recipe.'),
        })
        _logger.info(
            "TINT_NEW_APS_FAMILY_CREATED tint_wizard_id=%s family_id=%s colour_id=%s "
            "category_id=%s uom_id=%s attribute=%s user_id=%s",
            self.id, family.id, self.colour_code_id.id, self.base_variant_id.categ_id.id,
            self.base_variant_id.uom_id.id, attribute_name, self.env.user.id,
        )
        return family

    def _create_first_aps_formula_if_requested(self):
        self.ensure_one()
        if not self.new_formula_aps:
            return False
        if self.has_saved_formula:
            _logger.warning(
                "TINT_NEW_APS_BLOCKED tint_wizard_id=%s reason=saved_formula_exists user_id=%s",
                self.id, self.env.user.id,
            )
            raise ValidationError(_(
                'APS first-formula mode is only available when no saved formula exists.'
            ))
        if not self.new_formula_aps_customer_id:
            _logger.warning(
                "TINT_NEW_APS_BLOCKED tint_wizard_id=%s reason=missing_customer user_id=%s",
                self.id, self.env.user.id,
            )
            raise ValidationError(_('Customer is required when APS is selected.'))
        recipe = self._get_current_tint_recipe()
        if not recipe:
            raise ValidationError(_('Enter at least one colorant shot before creating an APS formula.'))

        family = self._prepare_first_aps_formula_family()
        version = self.env['tinting.formula.version'].create_aps_from_recipe(
            family=family,
            recipe=recipe,
            customer=self.new_formula_aps_customer_id,
            previous_version=None,
            change_summary=_('Initial APS recipe'),
        )
        self.write({
            'formula_id': family.id,
            'formula_version_id': version.id,
            'formula_applied': True,
        })
        _logger.info(
            "TINT_NEW_APS_CREATED tint_wizard_id=%s family_id=%s version_id=%s "
            "customer_id=%s recipe=%s user_id=%s",
            self.id, family.id, version.id, self.new_formula_aps_customer_id.id,
            recipe, self.env.user.id,
        )
        return version

    def action_create_tinted_product(self):
        self.ensure_one()
        if self.new_formula_aps and not self.formula_version_id:
            self._validate_selling_price_before_formula_decision()
            self._create_first_aps_formula_if_requested()
        return super().action_create_tinted_product()
