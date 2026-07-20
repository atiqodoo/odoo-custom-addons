# -*- coding: utf-8 -*-
"""Policy service for automatically approving only a formula family's first recipe."""

import logging

from odoo import _, api, fields, models
from odoo.tools import str2bool


_logger = logging.getLogger(__name__)


class TintingFormulaAutoApprovalPolicy(models.AbstractModel):
    _name = 'tinting.formula.auto.approval.policy'
    _description = 'Tinting Formula First-Version Auto-Approval Policy'

    _SETTING_KEY = 'paint_tinting.auto_approve_first_tint_formula'

    @api.model
    def is_enabled(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            self._SETTING_KEY, default='False',
        )
        enabled = str2bool(raw_value, default=False)
        _logger.debug(
            'FORMULA_AUTO_APPROVAL_SETTING_READ key=%s raw_value=%s enabled=%s user_id=%s',
            self._SETTING_KEY, raw_value, enabled, self.env.user.id,
        )
        return enabled

    @api.model
    def _eligibility(self, version, had_saved_recipe_before_capture):
        version.ensure_one()
        mo = version.source_mo_id
        enabled = self.is_enabled()
        checks = {
            'setting_enabled': enabled,
            'first_recipe': not had_saved_recipe_before_capture,
            'version_one': version.version_number == 1,
            'no_previous_version': not bool(version.previous_version_id),
            'manufacturing_origin': version.origin == 'mo',
            'tinting_mo': bool(mo and mo.is_tinting_mo),
            'approvable_state': version.state in ('draft', 'validated'),
            'not_aps': not bool(getattr(version, 'is_aps', False)),
        }
        eligible = all(checks.values())
        _logger.info(
            'FORMULA_AUTO_APPROVAL_DECISION version_id=%s family_id=%s mo_id=%s '
            'eligible=%s checks=%s user_id=%s',
            version.id, version.formula_id.id, mo.id, eligible, checks, self.env.user.id,
        )
        return eligible, checks

    @api.model
    def apply_if_eligible(self, version, had_saved_recipe_before_capture):
        """Approve and default a captured V1 without weakening normal manager approval."""
        version.ensure_one()
        eligible, checks = self._eligibility(version, had_saved_recipe_before_capture)
        if not eligible:
            return False

        # Reuse the normal recipe integrity checks, but intentionally do not call
        # action_approve(): configuration-driven approval is a system policy and
        # must not require the MO operator to belong to the manager group.
        version.sudo()._validate_for_approval()
        now = fields.Datetime.now()
        operator = self.env.user
        version.sudo().with_context(allow_formula_system_write=True).write({
            'state': 'approved',
            'approved_by_id': operator.id,
            'approved_date': now,
        })
        family = version.formula_id.sudo()
        family._set_default_version(version.sudo())
        version.sudo().message_post(body=_(
            'Version 1 was automatically approved and made the default under the '
            'Manufacturing first-formula approval setting. Source manufacturing '
            'order: %(mo)s. Operator: %(user)s.',
            mo=version.source_mo_id.display_name,
            user=operator.display_name,
        ))
        family.message_post(body=_(
            'Initial formula version %(version)s was automatically approved and made '
            'the default from manufacturing order %(mo)s.',
            version=version.display_name,
            mo=version.source_mo_id.display_name,
        ))
        _logger.warning(
            'FORMULA_AUTO_APPROVAL_APPLIED version_id=%s family_id=%s mo_id=%s '
            'default_version_id=%s approver_id=%s checks=%s',
            version.id, family.id, version.source_mo_id.id,
            family.default_version_id.id, operator.id, checks,
        )
        return True
