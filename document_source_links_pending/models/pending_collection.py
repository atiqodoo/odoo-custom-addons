from odoo import models


class PendingCollection(models.Model):
    _inherit = 'paint.pending.collection'

    def action_create_stock_moves(self):
        self.ensure_one()
        return super(PendingCollection, self.with_context(
            document_source_pending_id=self.id,
        )).action_create_stock_moves()

    def action_cancel(self):
        self.ensure_one()
        return super(PendingCollection, self.with_context(
            document_source_pending_id=self.id,
        )).action_cancel()
