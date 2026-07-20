import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    facts = env["product.movement.volume"].sudo().search([])
    _logger.info(
        "VOLUME_MIGRATION_RECALCULATE_START previous_version=%s fact_count=%s",
        version,
        len(facts),
    )
    result = facts._system_recalculate(reason="uom_reference_migration")
    _logger.info("VOLUME_MIGRATION_RECALCULATE_DONE result=%s", result)

