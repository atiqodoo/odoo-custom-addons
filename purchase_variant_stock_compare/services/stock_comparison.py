import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PurchaseStockComparison(models.AbstractModel):
    _name = 'purchase.stock.comparison'
    _description = 'Company and location scoped variant stock quantities'

    def _rows(self, wizard, products):
        _logger.debug('[RFQ_STOCK_COMPARE][STOCK_READ][START] company_id=%s location_id=%s count=%s',
                      wizard.company_id.id, wizard.location_id.id, len(products))
        try:
            products = products.with_company(wizard.company_id).with_context(
                allowed_company_ids=[wizard.company_id.id], location=wizard.location_id.id,
                warehouse=False, warehouse_id=False, from_date=False, to_date=False,
                lot_id=False, owner_id=False, package_id=False)
            products.invalidate_recordset(['qty_available', 'free_qty', 'incoming_qty', 'virtual_available'])
            quantities = products.read(['qty_available', 'free_qty', 'incoming_qty', 'virtual_available'])
            rows = [{
                'product_id': item['id'],
                'on_hand': item['qty_available'],
                'reserved': item['qty_available'] - item['free_qty'],
                'free_qty': item['free_qty'],
                'incoming_qty': item['incoming_qty'],
                'forecast_qty': item['virtual_available'],
                'is_original': item['id'] == wizard.product_id.id,
            } for item in quantities]
            rows.sort(key=lambda row: (not row['is_original'], -row['free_qty'], row['product_id']))
            _logger.debug('[RFQ_STOCK_COMPARE][STOCK_READ][END] count=%s', len(rows))
            return rows
        except Exception:
            _logger.exception('[RFQ_STOCK_COMPARE][STOCK_READ][ERROR] company_id=%s location_id=%s',
                              wizard.company_id.id, wizard.location_id.id)
            raise
