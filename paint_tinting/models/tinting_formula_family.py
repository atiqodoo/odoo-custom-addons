# -*- coding: utf-8 -*-
"""Formula-family behavior layered over the existing tinting.formula model."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaFamily(models.Model):
    _inherit = 'tinting.formula'

    version_ids = fields.One2many(
        'tinting.formula.version', 'formula_id', string='Recipe Versions', copy=False,
    )
    version_count = fields.Integer(compute='_compute_version_metrics')
    approved_version_count = fields.Integer(compute='_compute_version_metrics')
    latest_version_id = fields.Many2one(
        'tinting.formula.version', string='Latest Version', copy=False, readonly=True,
        domain="[('formula_id', '=', id)]",
    )
    default_version_id = fields.Many2one(
        'tinting.formula.version', string='Default Approved Version', copy=False, tracking=True,
        domain="[('formula_id', '=', id), ('state', '=', 'approved')]",
    )
    displayed_version_id = fields.Many2one(
        'tinting.formula.version', string='Displayed Recipe Version',
        compute='_compute_displayed_recipe', readonly=True,
    )
    displayed_version_state = fields.Selection(
        related='displayed_version_id.state', string='Displayed Version Status', readonly=True,
    )
    displayed_version_line_ids = fields.Many2many(
        'tinting.formula.version.line', string='Displayed Colorant Recipe',
        compute='_compute_displayed_recipe', readonly=True,
    )

    @api.depends('version_ids.state')
    def _compute_version_metrics(self):
        for family in self:
            family.version_count = len(family.version_ids)
            family.approved_version_count = len(family.version_ids.filtered(lambda v: v.state == 'approved'))

    @api.depends(
        'default_version_id', 'latest_version_id',
        'default_version_id.line_ids', 'latest_version_id.line_ids',
    )
    def _compute_displayed_recipe(self):
        for family in self:
            version = family.default_version_id or family.latest_version_id
            family.displayed_version_id = version
            family.displayed_version_line_ids = version.line_ids if version else False
            _logger.debug(
                "FORMULA_FAMILY_DISPLAY_RECIPE family_id=%s displayed_version_id=%s line_ids=%s",
                family.id, version.id, version.line_ids.ids if version else [],
            )

    @api.depends(
        'formula_line_ids.shots', 'formula_line_ids.ml_volume', 'formula_line_ids.qty_litres',
        'default_version_id.total_shots', 'default_version_id.total_ml',
        'default_version_id.total_litres', 'latest_version_id.total_shots',
        'latest_version_id.total_ml', 'latest_version_id.total_litres',
    )
    def _compute_totals(self):
        """Display version totals on the family while retaining legacy fallback."""
        for family in self:
            version = family.default_version_id or family.latest_version_id
            if version:
                family.total_shots = version.total_shots
                family.total_ml = version.total_ml
                family.total_litres = version.total_litres
                _logger.debug(
                    "FORMULA_FAMILY_TOTALS_FROM_VERSION family_id=%s version_id=%s "
                    "shots=%s ml=%s litres=%s",
                    family.id, version.id, version.total_shots,
                    version.total_ml, version.total_litres,
                )
            else:
                family.total_shots = sum(family.formula_line_ids.mapped('shots'))
                family.total_ml = sum(family.formula_line_ids.mapped('ml_volume'))
                family.total_litres = sum(family.formula_line_ids.mapped('qty_litres'))

    @api.constrains('colour_code_id', 'base_category_id', 'base_uom_id', 'base_attribute_name')
    def _check_normalized_identity_unique(self):
        service = self.env['tinting.formula.recipe.service']
        for family in self:
            if not family.colour_code_id or not family.base_category_id or not family.base_uom_id:
                continue
            candidates = self.search([
                ('id', '!=', family.id),
                ('colour_code_id', '=', family.colour_code_id.id),
                ('base_category_id', '=', family.base_category_id.id),
                ('base_uom_id', '=', family.base_uom_id.id),
            ])
            attribute = service.normalize_attribute(family.base_attribute_name)
            duplicate = candidates.filtered(
                lambda item: service.normalize_attribute(item.base_attribute_name) == attribute
            )[:1]
            if duplicate:
                raise ValidationError(_(
                    'Formula family %(duplicate)s already has this colour, category, UoM and base attribute.',
                    duplicate=duplicate.display_name,
                ))

    def get_legacy_shots_dict(self):
        self.ensure_one()
        return super().get_shots_dict()

    def get_shots_dict(self):
        self.ensure_one()
        if self.default_version_id:
            return self.default_version_id.get_shots_dict()
        return self.get_legacy_shots_dict()

    def _set_default_version(self, version):
        self.ensure_one()
        version.ensure_one()
        if version.formula_id != self:
            raise ValidationError(_('The selected version belongs to another formula family.'))
        if version.state not in ('approved', 'superseded'):
            raise ValidationError(_('Only an Approved or Superseded formula version can be the default.'))
        old_default = self.default_version_id
        if version.state == 'superseded':
            version.with_context(allow_formula_system_write=True).write({'state': 'approved'})
        self.with_context(allow_formula_system_write=True).write({
            'default_version_id': version.id,
            'latest_version_id': self.latest_version_id.id or version.id,
            'state': 'approved',
        })
        if old_default and old_default != version and old_default.state == 'approved':
            old_default.with_context(allow_formula_system_write=True).write({'state': 'superseded'})
        _logger.info(
            "FORMULA_DEFAULT_VERSION_CHANGED family_id=%s old_version_id=%s new_version_id=%s user_id=%s",
            self.id, old_default.id, version.id, self.env.user.id,
        )

    def action_approve(self):
        """Compatibility button: approve the latest Draft/Validated version."""
        self.ensure_one()
        version = self.env['tinting.formula.recipe.service'].sudo().ensure_legacy_version(self)
        version = self.latest_version_id or version
        if not version:
            raise ValidationError(_('Create a Draft formula version before approval.'))
        return version.with_env(self.env).action_approve()

    def action_reset_to_draft(self):
        """Approved recipes are immutable; resetting creates a new Draft version."""
        return self.action_create_draft_version()

    def action_create_draft_version(self):
        self.ensure_one()
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            raise ValidationError(_('Only Tinting Formula Managers can create manual versions.'))
        service = self.env['tinting.formula.recipe.service']
        service.ensure_legacy_version(self)
        source = self.latest_version_id or self.default_version_id
        recipe = source.get_shots_dict() if source else {}
        version_model = self.env['tinting.formula.version']
        if recipe:
            version = version_model.create_from_recipe(
                family=self,
                recipe=recipe,
                state='draft',
                origin='manual',
                previous_version=source,
                change_reason=_('Manual manager revision'),
            )
        else:
            version = version_model.create({
                'formula_id': self.id,
                'version_number': version_model._next_version_number(self),
                'previous_version_id': source.id if source else False,
                'state': 'draft',
                'origin': 'manual',
                'change_reason': _('Initial manual formula'),
            })
            self.with_context(allow_formula_system_write=True).write({'latest_version_id': version.id})
        _logger.info(
            "FORMULA_MANUAL_DRAFT_CREATED family_id=%s source_version_id=%s draft_version_id=%s user_id=%s",
            self.id, source.id, version.id, self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Draft Formula Version'),
            'res_model': 'tinting.formula.version',
            'res_id': version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_versions(self):
        self.ensure_one()
        self.env['tinting.formula.recipe.service'].ensure_legacy_version(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versions for %s', self.display_name),
            'res_model': 'tinting.formula.version',
            'view_mode': 'list,form',
            'domain': [('formula_id', '=', self.id)],
            'context': {'default_formula_id': self.id},
        }
