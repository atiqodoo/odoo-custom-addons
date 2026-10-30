from odoo import models


class CollectPendingItems(models.TransientModel):
    _inherit = 'collect.pending.items.wizard'

    def _create_return_stock_move(self, collection_line, qty):
        self.ensure_one()
        return super(CollectPendingItems, self.with_context(
            document_source_pending_id=collection_line.pending_collection_id.id,
        ))._create_return_stock_move(collection_line, qty)
