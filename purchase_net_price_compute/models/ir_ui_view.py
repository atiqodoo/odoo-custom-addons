import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _cleanup_lpo_legacy_signature_metadata(self):
        legacy_views = self.sudo().search([
            ('key', '=', 'purchase_product_matrix.grid_purchaseorder_inherit'),
            ('arch_db', 'ilike', 'Rubber Stamp Box'),
        ])
        for view in legacy_views:
            _logger.info(
                "Deactivating legacy duplicate LPO signature metadata view id=%s key=%s name=%s",
                view.id,
                view.key,
                view.name,
            )
            view.active = False
        return True
