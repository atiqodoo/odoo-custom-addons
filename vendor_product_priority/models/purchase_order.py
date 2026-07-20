import logging

from odoo import models


_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _get_action_add_from_catalog_extra_context(self):
        self.ensure_one()
        context = super()._get_action_add_from_catalog_extra_context()
        removed_hard_filter = context.pop('search_default_seller_ids', None)
        context.update({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'vendor_priority_search': bool(self.partner_id),
            'vendor_priority_source': 'purchase_catalog',
        })
        _logger.info(
            'VPS_CATALOG_CONTEXT order=%s vendor=%s company=%s priority_enabled=%s '
            'removed_default_vendor_filter=%r',
            self.id,
            self.partner_id.id,
            self.company_id.id,
            bool(self.partner_id),
            removed_hard_filter,
        )
        return context

