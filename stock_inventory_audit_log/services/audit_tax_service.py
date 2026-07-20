import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockAuditTaxService(models.AbstractModel):
    _name = 'stock.audit.tax.service'
    _description = 'Stock Audit Tax Snapshot Service'

    def get_vat_amount_per_unit(self, product, company, unit_cost, currency):
        taxes = product.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == company)
        if not taxes:
            return 0.0
        try:
            result = taxes.compute_all(
                unit_cost,
                currency=currency,
                quantity=1.0,
                product=product,
                partner=False,
            )
        except Exception:
            _logger.exception(
                "AUDIT_TAX_COMPUTE_FAILED product_id=%s company_id=%s unit_cost=%s",
                product.id,
                company.id,
                unit_cost,
            )
            return 0.0
        return (result.get('total_included') or 0.0) - (result.get('total_excluded') or 0.0)
