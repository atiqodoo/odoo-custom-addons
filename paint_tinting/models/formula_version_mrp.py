# -*- coding: utf-8 -*-
"""Manufacturing integration for immutable formula versions."""

import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class MrpProductionFormulaVersion(models.Model):
    _inherit = 'mrp.production'

    formula_version_id = fields.Many2one(
        'tinting.formula.version', string='Captured Formula Version', copy=False,
        readonly=True, tracking=True,
        help='Exact immutable formula recipe used or captured by this manufacturing order.',
    )

    def _auto_save_tinting_formula(self):
        self.ensure_one()
        if self.state != 'done':
            _logger.warning(
                "FORMULA_MO_CAPTURE_DEFERRED mo_id=%s mo=%s state=%s reason=not_done",
                self.id, self.name, self.state,
            )
            return False
        _logger.info(
            "FORMULA_MO_CAPTURE_START mo_id=%s mo=%s bom_id=%s user_id=%s",
            self.id, self.name, self.bom_id.id, self.env.user.id,
        )
        version = self.env['tinting.formula.recipe.service'].sudo().capture_from_mo(self)
        _logger.info(
            "FORMULA_MO_CAPTURE_DONE mo_id=%s family_id=%s version_id=%s",
            self.id, self.formula_id.id, version.id if version else False,
        )
        return bool(version)
