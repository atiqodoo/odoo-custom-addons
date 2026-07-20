# -*- coding: utf-8 -*-
"""Explicit confirmation and validation for UI bulk approval."""

import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class TintingFormulaBulkApproveWizard(models.TransientModel):
    _name = 'tinting.formula.bulk.approve.wizard'
    _description = 'Bulk Approve Tinting Formula Versions'

    version_ids = fields.Many2many('tinting.formula.version', required=True, readonly=True)
    version_count = fields.Integer(compute='_compute_version_count')
    default_policy = fields.Selection([
        ('approve_only', 'Approve and make available'),
        ('set_default', 'Approve and set as family default'),
    ], default='approve_only', required=True)
    confirmation_note = fields.Text()

    def _compute_version_count(self):
        for wizard in self:
            wizard.version_count = len(wizard.version_ids)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            raise AccessError(_('Only Tinting Formula Managers can bulk approve versions.'))
        versions = self.version_ids
        if not versions:
            raise ValidationError(_('Select at least one formula version.'))
        invalid_versions = versions.filtered(
            lambda version: version.state not in ('draft', 'validated')
        )
        if invalid_versions:
            _logger.warning(
                "FORMULA_RETROACTIVE_BULK_APPROVAL_BLOCKED version_ids=%s "
                "invalid_version_ids=%s invalid_states=%s manager_id=%s",
                versions.ids, invalid_versions.ids, invalid_versions.mapped('state'),
                self.env.user.id,
            )
            raise ValidationError(_(
                'Retroactive bulk approval accepts only Draft or Validated versions. '
                'Remove these selections: %s',
                ', '.join(invalid_versions.mapped('display_name')),
            ))
        if self.default_policy == 'set_default':
            duplicate_families = versions.mapped('formula_id').filtered(
                lambda family: len(versions.filtered(lambda version: version.formula_id == family)) > 1
            )
            if duplicate_families:
                raise ValidationError(_(
                    'Only one selected version per formula family can be made default. Conflicts: %s',
                    ', '.join(duplicate_families.mapped('display_name')),
                ))
        versions._validate_for_approval()
        versions.action_approve(set_default=self.default_policy == 'set_default')
        if self.confirmation_note:
            for version in versions:
                version.message_post(body=_('Bulk approval note: %s', self.confirmation_note))
        _logger.info(
            "FORMULA_RETROACTIVE_BULK_APPROVAL_DONE version_ids=%s policy=%s manager_id=%s",
            versions.ids, self.default_policy, self.env.user.id,
        )
        return {'type': 'ir.actions.act_window_close'}


class TintingFormulaVersionBulkAction(models.Model):
    _inherit = 'tinting.formula.version'

    def action_open_bulk_approval_wizard(self):
        if not self.env.user.has_group('paint_tinting.group_tint_formula_manager'):
            _logger.warning(
                "FORMULA_RETROACTIVE_BULK_APPROVAL_ACCESS_DENIED version_ids=%s user_id=%s",
                self.ids, self.env.user.id,
            )
            raise AccessError(_('Only Tinting Formula Managers can bulk approve versions.'))
        versions = self.exists()
        if not versions:
            raise ValidationError(_('Select at least one formula version.'))
        wizard = self.env['tinting.formula.bulk.approve.wizard'].create({
            'version_ids': [(6, 0, versions.ids)],
        })
        _logger.info(
            "FORMULA_RETROACTIVE_BULK_APPROVAL_OPEN version_ids=%s states=%s manager_id=%s",
            versions.ids, versions.mapped('state'), self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Retroactively Approve Formula Versions'),
            'res_model': 'tinting.formula.bulk.approve.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
