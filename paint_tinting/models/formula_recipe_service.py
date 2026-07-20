# -*- coding: utf-8 -*-
"""Shared recipe normalization, comparison, and MO-capture services."""

import hashlib
import json
import logging

from odoo import _, api, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaRecipeService(models.AbstractModel):
    _name = 'tinting.formula.recipe.service'
    _description = 'Tinting Formula Recipe Service'

    @api.model
    def normalize_attribute(self, value):
        normalized = str(value or '').strip().lower()
        if '/' in normalized:
            normalized = normalized.split('/', 1)[0].strip()
        return normalized

    @api.model
    def normalize_code(self, value):
        return str(value or '').strip().upper()

    @api.model
    def normalize_shots(self, value):
        return round(float(value or 0.0), 2)

    @api.model
    def normalize_recipe(self, recipe):
        """Return a sorted {CODE: shots} recipe containing non-zero values."""
        normalized = {}
        for code, shots in (recipe or {}).items():
            clean_code = self.normalize_code(code)
            clean_shots = self.normalize_shots(shots)
            if clean_code and clean_shots > 0:
                normalized[clean_code] = clean_shots
        result = dict(sorted(normalized.items()))
        _logger.debug("FORMULA_RECIPE_NORMALIZED input=%s result=%s", recipe, result)
        return result

    @api.model
    def signature(self, recipe):
        normalized = self.normalize_recipe(recipe)
        payload = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        _logger.debug("FORMULA_RECIPE_SIGNATURE payload=%s signature=%s", payload, digest)
        return digest

    @api.model
    def diff(self, old_recipe, new_recipe):
        old = self.normalize_recipe(old_recipe)
        new = self.normalize_recipe(new_recipe)
        changes = []
        for code in sorted(set(old) | set(new)):
            old_value = old.get(code, 0.0)
            new_value = new.get(code, 0.0)
            if old_value == new_value:
                continue
            if not old_value:
                change_type = 'added'
            elif not new_value:
                change_type = 'removed'
            else:
                change_type = 'changed'
            changes.append({
                'code': code,
                'type': change_type,
                'old': old_value,
                'new': new_value,
                'delta': round(new_value - old_value, 2),
            })
        _logger.debug("FORMULA_RECIPE_DIFF old=%s new=%s changes=%s", old, new, changes)
        return changes

    @api.model
    def recipe_from_bom(self, bom):
        recipe = {}
        products = {}
        for line in bom.bom_line_ids.filtered('is_colorant_line'):
            code = self.normalize_code(line.product_id.product_tmpl_id.colorant_code)
            shots = self.normalize_shots(line.colorant_shots)
            if code and shots > 0:
                if code in recipe:
                    raise ValidationError(_("BOM contains duplicate colorant code %s.", code))
                recipe[code] = shots
                products[code] = line.product_id
        recipe = self.normalize_recipe(recipe)
        _logger.info(
            "FORMULA_BOM_RECIPE_EXTRACTED bom_id=%s bom=%s colorants=%s recipe=%s",
            bom.id, bom.display_name, len(recipe), recipe,
        )
        return recipe, products

    @api.model
    def find_family(self, colour, category, uom, attribute_name=''):
        attribute = self.normalize_attribute(attribute_name)
        candidates = self.env['tinting.formula'].with_context(active_test=False).search([
            ('colour_code_id', '=', colour.id),
            ('base_category_id', '=', category.id),
            ('base_uom_id', '=', uom.id),
        ])
        family = candidates.filtered(
            lambda item: self.normalize_attribute(item.base_attribute_name) == attribute
        )[:1]
        _logger.debug(
            "FORMULA_FAMILY_LOOKUP colour_id=%s category_id=%s uom_id=%s attribute=%s "
            "candidate_ids=%s result_id=%s",
            colour.id, category.id, uom.id, attribute, candidates.ids, family.id,
        )
        return family

    @api.model
    def ensure_legacy_version(self, family):
        """Lazily preserve an existing pre-versioning recipe as Version 1."""
        family = family.sudo()
        family.ensure_one()
        if family.version_ids or not family.formula_line_ids:
            return family.latest_version_id or family.default_version_id

        recipe = family.get_legacy_shots_dict()
        state = family.state if family.state in ('draft', 'validated', 'approved') else 'validated'
        _logger.warning(
            "FORMULA_LEGACY_MIGRATION_START family_id=%s name=%s state=%s recipe=%s",
            family.id, family.name, state, recipe,
        )
        version = self.env['tinting.formula.version'].sudo().create_from_recipe(
            family=family,
            recipe=recipe,
            state=state,
            origin='migration',
            source_mo=family.source_mo_id,
            source_bom=family.source_bom_id,
            notes=_('Migrated from the original non-versioned formula.'),
            change_reason=_('Initial legacy recipe migration'),
        )
        values = {'latest_version_id': version.id}
        if state == 'approved':
            values['default_version_id'] = version.id
        family.sudo().with_context(allow_formula_system_write=True).write(values)
        _logger.warning(
            "FORMULA_LEGACY_MIGRATION_DONE family_id=%s version_id=%s version=%s",
            family.id, version.id, version.display_name,
        )
        return version

    @api.model
    def capture_from_mo(self, mo):
        """Create a validated version only when the completed MO recipe is new."""
        mo.ensure_one()
        bom = mo.bom_id
        colour = bom.colour_code_id
        base_product = bom.base_variant_id
        if not colour or not base_product:
            _logger.warning(
                "FORMULA_MO_CAPTURE_SKIPPED mo_id=%s reason=missing_identity colour_id=%s base_id=%s",
                mo.id, colour.id, base_product.id,
            )
            return False

        category = base_product.categ_id
        uom = bom.pack_size_uom_id or base_product.uom_id
        attribute_value = base_product.product_template_attribute_value_ids[:1]
        attribute_name = self.normalize_attribute(attribute_value.name if attribute_value else '')
        recipe, products = self.recipe_from_bom(bom)
        if not recipe:
            _logger.warning("FORMULA_MO_CAPTURE_SKIPPED mo_id=%s reason=empty_recipe", mo.id)
            return False

        family = self.find_family(colour, category, uom, attribute_name)
        had_saved_recipe_before_capture = bool(
            family and (family.sudo().version_ids or family.sudo().formula_line_ids)
        )
        _logger.info(
            "FORMULA_MO_CAPTURE_IDENTITY mo_id=%s family_id=%s "
            "had_saved_recipe_before_capture=%s colour_id=%s category_id=%s "
            "uom_id=%s attribute=%s",
            mo.id, family.id, had_saved_recipe_before_capture, colour.id,
            category.id, uom.id, attribute_name,
        )
        if not family:
            family_values = {
                'colour_code_id': colour.id,
                'base_category_id': category.id,
                'base_uom_id': uom.id,
                'base_attribute_id': attribute_value.id if attribute_value else False,
                'state': 'validated',
                'source_mo_id': mo.id,
                'source_bom_id': bom.id,
                'notes': _('Formula family created automatically from MO %s.', mo.name),
            }
            family = self.env['tinting.formula'].sudo().create(family_values)
            _logger.info(
                "FORMULA_FAMILY_CREATED_FROM_MO mo_id=%s family_id=%s identity=%s",
                mo.id, family.id, family.name,
            )
        else:
            self.ensure_legacy_version(family)

        recipe_signature = self.signature(recipe)
        existing = family.version_ids.filtered(
            lambda version: version.recipe_signature == recipe_signature
        )[:1]
        if existing:
            mo.with_context(allow_formula_system_write=True).write({
                'formula_id': family.id,
                'formula_version_id': existing.id,
            })
            _logger.info(
                "FORMULA_MO_CAPTURE_MATCH mo_id=%s family_id=%s version_id=%s signature=%s",
                mo.id, family.id, existing.id, recipe_signature,
            )
            return existing

        previous = family.latest_version_id
        version = self.env['tinting.formula.version'].sudo().create_from_recipe(
            family=family,
            recipe=recipe,
            products=products,
            state='validated',
            origin='mo',
            previous_version=previous,
            source_mo=mo,
            source_bom=bom,
            notes=_('Automatically captured from completed MO %s.', mo.name),
            change_reason=_('Recipe changed on completed manufacturing order'),
        )
        family.sudo().with_context(allow_formula_system_write=True).write({
            'latest_version_id': version.id,
            'source_mo_id': mo.id,
            'source_bom_id': bom.id,
            'state': 'validated',
        })
        mo.with_context(allow_formula_system_write=True).write({
            'formula_id': family.id,
            'formula_version_id': version.id,
        })
        auto_approved = self.env[
            'tinting.formula.auto.approval.policy'
        ].apply_if_eligible(
            version,
            had_saved_recipe_before_capture=had_saved_recipe_before_capture,
        )
        _logger.info(
            "FORMULA_MO_CAPTURE_VERSION_CREATED mo_id=%s family_id=%s version_id=%s "
            "version_number=%s previous_id=%s signature=%s auto_approved=%s final_state=%s "
            "default_version_id=%s",
            mo.id, family.id, version.id, version.version_number, previous.id,
            recipe_signature, auto_approved, version.state, family.default_version_id.id,
        )
        return version
