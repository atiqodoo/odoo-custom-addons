from odoo import models


class StockAuditMatchingService(models.AbstractModel):
    _name = 'stock.audit.matching.service'
    _description = 'Stock Audit Draft Matching Service'

    def find_draft_for_quant(self, quant):
        AuditLog = self.env['stock.audit.log'].sudo()
        if quant.id:
            log = AuditLog.search([
                ('quant_id', '=', quant.id),
                ('state', '=', 'draft'),
            ], order='timestamp_counted desc, id desc', limit=1)
            if log:
                return log

        domain = [
            ('state', '=', 'draft'),
            ('product_id', '=', quant.product_id.id),
            ('location_id', '=', quant.location_id.id),
            ('company_id', '=', quant.company_id.id),
            ('lot_id', '=', quant.lot_id.id or False),
            ('package_id', '=', quant.package_id.id or False),
            ('owner_id', '=', quant.owner_id.id or False),
        ]
        return AuditLog.search(domain, order='timestamp_counted desc, id desc', limit=1)
