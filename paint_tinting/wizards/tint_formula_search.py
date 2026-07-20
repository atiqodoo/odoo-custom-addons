# -*- coding: utf-8 -*-
"""Search and apply usable formula versions from the operational tint wizard."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class TintFormulaSearchWizard(models.TransientModel):
    _name = 'tint.formula.search.wizard'
    _description = 'Search and Apply Tint Formula Version'

    tint_wizard_id = fields.Many2one(
        'tint.wizard', required=True, readonly=True, ondelete='cascade',
    )
    available_formula_version_ids = fields.Many2many(
        'tinting.formula.version', compute='_compute_available_formula_versions',
    )
    formula_version_id = fields.Many2one(
        'tinting.formula.version', string='Approved Formula Version', required=True,
        domain="[('id', 'in', available_formula_version_ids)]",
    )
    formula_id = fields.Many2one(
        related='formula_version_id.formula_id', string='Formula', readonly=True,
    )
    state = fields.Selection(related='formula_version_id.state', readonly=True)
    change_summary = fields.Text(related='formula_version_id.change_summary', readonly=True)
    is_aps = fields.Boolean(related='formula_version_id.is_aps', readonly=True)
    aps_customer_id = fields.Many2one(
        related='formula_version_id.aps_customer_id', string='APS Customer', readonly=True,
    )

    @api.depends('tint_wizard_id', 'tint_wizard_id.base_variant_id',
                 'tint_wizard_id.colour_code_id')
    def _compute_available_formula_versions(self):
        for search_wizard in self:
            tint_wizard = search_wizard.tint_wizard_id
            family = tint_wizard._get_tint_formula_family() if tint_wizard else False
            versions = family.sudo().version_ids.filtered(
                lambda version: version.active and version.state in ('approved', 'superseded')
            ) if family else self.env['tinting.formula.version']
            search_wizard.available_formula_version_ids = versions
            _logger.debug(
                "TINT_FORMULA_SEARCH_AVAILABLE search_wizard_id=%s tint_wizard_id=%s "
                "family_id=%s version_ids=%s",
                search_wizard.id, tint_wizard.id, family.id if family else False, versions.ids,
            )

    def action_apply_formula(self):
        self.ensure_one()
        if self.formula_version_id not in self.available_formula_version_ids:
            raise ValidationError(_('Select an Approved or Superseded formula version.'))
        tint_wizard = self.tint_wizard_id.exists()
        if not tint_wizard:
            raise ValidationError(_('The original Tinting Wizard has expired. Please start again.'))

        _logger.info(
            "TINT_FORMULA_SEARCH_APPLY search_wizard_id=%s tint_wizard_id=%s "
            "family_id=%s version_id=%s is_aps=%s customer_id=%s user_id=%s",
            self.id, tint_wizard.id, self.formula_version_id.formula_id.id,
            self.formula_version_id.id, self.formula_version_id.is_aps,
            self.formula_version_id.aps_customer_id.id, self.env.user.id,
        )
        tint_wizard._apply_formula_version(self.formula_version_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tint New Paint'),
            'res_model': 'tint.wizard',
            'res_id': tint_wizard.id,
            'view_mode': 'form',
            'view_id': self.env.ref('paint_tinting.view_tint_wizard_form').id,
            'target': 'new',
        }


class TintWizardFormulaSearch(models.TransientModel):
    _inherit = 'tint.wizard'

    @api.depends('colour_code_id', 'base_variant_id')
    def _compute_available_formulas(self):
        for wizard in self:
            family = wizard._get_tint_formula_family() if (
                wizard.colour_code_id and wizard.base_variant_id
            ) else False
            versions = family.sudo().version_ids.filtered(
                lambda version: version.active and version.state in ('approved', 'superseded')
            ) if family else self.env['tinting.formula.version']
            wizard.available_formulas = len(versions)
            _logger.debug(
                "TINT_FORMULA_USABLE_COUNT tint_wizard_id=%s colour_id=%s base_id=%s "
                "family_id=%s version_ids=%s count=%s",
                wizard.id, wizard.colour_code_id.id, wizard.base_variant_id.id,
                family.id if family else False, versions.ids, len(versions),
            )

    def action_view_available_formulas(self):
        self.ensure_one()
        family = self._get_tint_formula_family()
        versions = family.sudo().version_ids.filtered(
            lambda version: version.active and version.state in ('approved', 'superseded')
        ) if family else self.env['tinting.formula.version']
        if not versions:
            raise ValidationError(_(
                'No Approved or Superseded formula version matches this colour, '
                'base category, pack size and base attribute.'
            ))
        search_wizard = self.env['tint.formula.search.wizard'].create({
            'tint_wizard_id': self.id,
            'formula_version_id': self.formula_version_id.id
            if self.formula_version_id in versions else (
                family.default_version_id.id
                if family.default_version_id in versions else versions[0].id
            ),
        })
        _logger.info(
            "TINT_FORMULA_SEARCH_OPEN tint_wizard_id=%s search_wizard_id=%s "
            "family_id=%s version_ids=%s selected_version_id=%s user_id=%s",
            self.id, search_wizard.id, family.id, versions.ids,
            search_wizard.formula_version_id.id, self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Search Approved Formula Versions'),
            'res_model': 'tint.formula.search.wizard',
            'res_id': search_wizard.id,
            'view_mode': 'form',
            'view_id': self.env.ref('paint_tinting.view_tint_formula_search_form').id,
            'target': 'new',
        }
