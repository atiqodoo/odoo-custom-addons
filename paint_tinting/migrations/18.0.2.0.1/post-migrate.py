# -*- coding: utf-8 -*-
"""Create Version 1 snapshots for every pre-versioning formula family."""

import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    families = env['tinting.formula'].with_context(active_test=False).search([
        ('formula_line_ids', '!=', False),
        ('version_ids', '=', False),
    ])
    _logger.warning(
        "FORMULA_VERSION_MIGRATION_START previous_module_version=%s family_count=%s",
        version, len(families),
    )
    service = env['tinting.formula.recipe.service'].sudo()
    migrated = 0
    failed = []
    for family in families:
        try:
            with cr.savepoint():
                if service.ensure_legacy_version(family):
                    migrated += 1
        except Exception as exc:
            failed.append((family.id, str(exc)))
            _logger.exception(
                "FORMULA_VERSION_MIGRATION_FAMILY_FAILED family_id=%s name=%s",
                family.id, family.display_name,
            )
    _logger.warning(
        "FORMULA_VERSION_MIGRATION_DONE migrated=%s failed=%s failures=%s",
        migrated, len(failed), failed,
    )
