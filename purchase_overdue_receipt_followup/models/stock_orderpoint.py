from odoo import models


class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

    def _procure_orderpoint_confirm(self, use_new_cursor=False, company_id=None, raise_user_error=True):
        # Scan before core's batch cursor handling so this code never uses a closed cursor.
        enabled = self.filtered(lambda op: op.active and op.trigger == 'auto'
                                and op.company_id.receipt_followup_enabled)
        if enabled:
            # Scheduler/POS may run as stock users. Elevation is limited to recording
            # internal alerts for these already selected companies, never purchasing.
            self.env['purchase.receipt.followup'].sudo()._scan_orderpoints(enabled.sudo())
        return super()._procure_orderpoint_confirm(
            use_new_cursor=use_new_cursor, company_id=company_id, raise_user_error=raise_user_error)
