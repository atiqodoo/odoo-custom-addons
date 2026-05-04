# -*- coding: utf-8 -*-

from odoo import api, models


class StockCardReport(models.AbstractModel):
    _name = 'report.enhanced_stock_card.report_stock_card_document'
    _description = 'Stock Card Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Prepare data for QWeb report template"""
        if not data:
            # Called without wizard, get wizard from docids
            wizard = self.env['stock.card.wizard'].browse(docids)
            data = wizard._prepare_stock_card_data()
        
        return {
            'doc_ids': docids,
            'doc_model': 'stock.card.wizard',
            'data': data,
            'docs': self.env['stock.card.wizard'].browse(docids),
        }
