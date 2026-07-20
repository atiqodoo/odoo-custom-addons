# -*- coding: utf-8 -*-
"""Carry altered tint recipes through the existing-product duplicate flow."""

import json
import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintWizardDuplicateRecipeHandoff(models.TransientModel):
    _inherit = 'tint.wizard'

    def action_create_tinted_product(self):
        result = super().action_create_tinted_product()
        if not isinstance(result, dict) or result.get('res_model') != 'tint.product.exists.wizard':
            return result

        exists_wizard = self.env['tint.product.exists.wizard'].browse(result.get('res_id')).exists()
        if not exists_wizard:
            return result

        payload = {}
        recipe = {}
        for line in self.colorant_line_ids.filtered(lambda item: item.shots > 0):
            if not line.colorant_id or not line.colorant_code:
                continue
            shots = round(line.shots, 2)
            recipe[line.colorant_code] = shots
            payload[line.colorant_code] = {
                'colorant_id': line.colorant_id.id,
                'shots': shots,
            }

        source_recipe = {}
        if exists_wizard.mo_id and exists_wizard.mo_id.bom_id:
            source_recipe, _products = self.env[
                'tinting.formula.recipe.service'
            ].recipe_from_bom(exists_wizard.mo_id.bom_id)
        service = self.env['tinting.formula.recipe.service']
        changed = service.signature(recipe) != service.signature(source_recipe)
        changes = service.diff(source_recipe, recipe) if changed else []
        summary_lines = []
        for change in changes:
            if change['type'] == 'added':
                summary_lines.append(_('%(code)s added: %(new).2f shots', **change))
            elif change['type'] == 'removed':
                summary_lines.append(_('%(code)s removed: %(old).2f shots', **change))
            else:
                summary_lines.append(_(
                    '%(code)s changed: %(old).2f -> %(new).2f shots', **change,
                ))
        exists_wizard.write({
            'recipe_override_json': json.dumps(payload, sort_keys=True),
            'has_recipe_override': changed,
            'recipe_change_summary': '\n'.join(summary_lines) or _('No recipe changes detected.'),
        })
        _logger.info(
            "TINT_EXISTS_RECIPE_HANDOFF wizard_id=%s exists_wizard_id=%s source_mo_id=%s "
            "changed=%s source_recipe=%s requested_recipe=%s changes=%s",
            self.id, exists_wizard.id, exists_wizard.mo_id.id, changed,
            source_recipe, recipe, changes,
        )
        return result


class TintProductExistsRecipeHandoff(models.TransientModel):
    _inherit = 'tint.product.exists.wizard'

    recipe_override_json = fields.Text(readonly=True)
    has_recipe_override = fields.Boolean(readonly=True)
    recipe_change_summary = fields.Text(readonly=True)

    def action_open_mo(self):
        result = super().action_open_mo()
        if self.has_recipe_override and self.recipe_override_json:
            context = dict(result.get('context') or {})
            context.update({
                'tint_recipe_override_json': self.recipe_override_json,
                'tint_recipe_change_summary': self.recipe_change_summary,
            })
            result['context'] = context
            _logger.info(
                "TINT_EXISTS_RECIPE_CONTEXT_FORWARDED exists_wizard_id=%s mo_id=%s summary=%s",
                self.id, self.mo_id.id, self.recipe_change_summary,
            )
        return result


class MrpProductionDuplicateRecipeRevision(models.TransientModel):
    _inherit = 'mrp.production.duplicate.wizard'

    recipe_override_json = fields.Text(readonly=True)
    has_recipe_override = fields.Boolean(compute='_compute_has_recipe_override')
    recipe_change_summary = fields.Text(readonly=True)

    def _compute_has_recipe_override(self):
        for wizard in self:
            wizard.has_recipe_override = bool(wizard.recipe_override_json)

    def _prepare_duplicate_bom(self):
        self.ensure_one()
        source_bom = super()._prepare_duplicate_bom()
        if not self.recipe_override_json:
            return source_bom
        try:
            payload = json.loads(self.recipe_override_json)
        except (TypeError, ValueError) as exc:
            _logger.exception(
                "TINT_DUPLICATE_RECIPE_JSON_INVALID wizard_id=%s payload=%s",
                self.id, self.recipe_override_json,
            )
            raise ValidationError(_('The revised tint recipe is not valid JSON.')) from exc

        requested_recipe = {
            code: data.get('shots', 0.0)
            for code, data in payload.items()
            if isinstance(data, dict)
        }
        service = self.env['tinting.formula.recipe.service']
        source_recipe, _products = service.recipe_from_bom(source_bom)
        if service.signature(requested_recipe) == service.signature(source_recipe):
            _logger.info(
                "TINT_DUPLICATE_RECIPE_UNCHANGED wizard_id=%s source_bom_id=%s recipe=%s",
                self.id, source_bom.id, source_recipe,
            )
            return source_bom

        revision_values = {
            'code': _('%(code)s / Recipe Revision', code=source_bom.code or source_bom.display_name),
            'active': False,
            'tinting_notes': '%s\n%s' % (
                source_bom.tinting_notes or '',
                _('Private recipe revision from duplicate wizard: %s',
                  self.recipe_change_summary or _('colorant recipe changed')),
            ),
        }
        revision = source_bom.copy(revision_values)
        revision.bom_line_ids.filtered('is_colorant_line').unlink()

        created_lines = self.env['mrp.bom.line']
        for code, data in sorted(payload.items()):
            shots = service.normalize_shots(data.get('shots')) if isinstance(data, dict) else 0.0
            if shots <= 0:
                continue
            product = self.env['product.product'].browse(data.get('colorant_id')).exists()
            if not product or not product.product_tmpl_id.is_colorant:
                raise ValidationError(_('Colorant %s is not mapped to a valid product.', code))
            actual_code = service.normalize_code(product.product_tmpl_id.colorant_code)
            if actual_code != service.normalize_code(code):
                raise ValidationError(_(
                    'Colorant mapping mismatch: spreadsheet/wizard code %(code)s maps to product code %(actual)s.',
                    code=code, actual=actual_code or '-',
                ))
            created_lines |= self.env['mrp.bom.line'].create({
                'bom_id': revision.id,
                'product_id': product.id,
                'product_qty': shots * 0.616 / 1000.0,
                'product_uom_id': product.uom_id.id,
                'is_colorant_line': True,
                'colorant_shots': shots,
                'unit_cost_excl_vat': product.standard_price,
            })
        if not created_lines:
            revision.unlink()
            raise ValidationError(_('The revised recipe must contain at least one colorant.'))

        final_recipe, _products = service.recipe_from_bom(revision)
        _logger.info(
            "TINT_DUPLICATE_RECIPE_BOM_CREATED wizard_id=%s source_bom_id=%s revision_bom_id=%s "
            "source_recipe=%s requested_recipe=%s final_recipe=%s line_ids=%s",
            self.id, source_bom.id, revision.id, source_recipe,
            requested_recipe, final_recipe, created_lines.ids,
        )
        return revision
