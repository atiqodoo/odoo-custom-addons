# -*- coding: utf-8 -*-
"""Refresh family display totals after introducing version-backed recipes."""

import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    families = env['tinting.formula'].with_context(active_test=False).search([])
    fields_to_refresh = ['total_shots', 'total_ml', 'total_litres']
    _logger.warning(
        "FORMULA_FAMILY_TOTAL_REFRESH_START previous_module_version=%s family_count=%s",
        version, len(families),
    )
    # Existing stored values are not automatically queued just because the
    # compute implementation changed. Invoke the version-aware compute once.
    families._compute_totals()
    env.flush_all()
    _logger.warning(
        "FORMULA_FAMILY_TOTAL_REFRESH_DONE family_count=%s fields=%s",
        len(families), fields_to_refresh,
    )
