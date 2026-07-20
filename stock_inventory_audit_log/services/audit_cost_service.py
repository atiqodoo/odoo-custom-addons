from odoo import models


class StockAuditCostService(models.AbstractModel):
    _name = 'stock.audit.cost.service'
    _description = 'Stock Audit Cost Snapshot Service'

    def get_cost_values(self, product, company):
        product = product.with_company(company)
        return {
            'unit_cost_excl_vat': product.standard_price or 0.0,
            'currency_id': company.currency_id.id,
        }
