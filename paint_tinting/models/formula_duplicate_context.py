# -*- coding: utf-8 -*-
"""Forward a staged tint recipe from an MO form into duplicate actions."""

import logging

from odoo import models


_logger = logging.getLogger(__name__)


class MrpProductionFormulaDuplicateContext(models.Model):
    _inherit = 'mrp.production'

    def _inject_tint_recipe_defaults(self, action):
        recipe_json = self.env.context.get('tint_recipe_override_json')
        if not recipe_json or not isinstance(action, dict):
            return action
        context = dict(action.get('context') or {})
        context.update({
            'default_recipe_override_json': recipe_json,
            'default_recipe_change_summary': self.env.context.get('tint_recipe_change_summary'),
        })
        action['context'] = context
        _logger.info(
            "TINT_DUPLICATE_RECIPE_DEFAULTS_INJECTED mo_id=%s action_model=%s summary=%s",
            self.id, action.get('res_model'), context.get('default_recipe_change_summary'),
        )
        return action

    def action_open_duplicate_wizard(self):
        self.ensure_one()
        return self._inject_tint_recipe_defaults(super().action_open_duplicate_wizard())

    def action_duplicate_single(self):
        self.ensure_one()
        if self.env.context.get('tint_recipe_override_json'):
            return self.action_open_duplicate_wizard()
        return super().action_duplicate_single()
