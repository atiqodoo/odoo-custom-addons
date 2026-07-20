import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    facts = env["product.movement.volume"].sudo().search([])
    _logger.info(
        "VOLUME_POST_MIGRATE_TINTING_LINEAGE_START version=%s fact_count=%s",
        version,
        len(facts),
    )
    result = facts._system_recalculate(reason="post_migrate_tinting_lineage")
    _logger.info("VOLUME_POST_MIGRATE_TINTING_LINEAGE_DONE result=%s", result)
