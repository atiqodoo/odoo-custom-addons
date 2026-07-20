# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class StockCardWizardContactExcel(models.TransientModel):
    _inherit = 'stock.card.wizard'

    def _create_excel_report(self, workbook, data):
        if data.get('report_mode') != 'contact_transactions':
            return super()._create_excel_report(workbook, data)
        return self._create_contact_excel_report(workbook, data)

    def _create_contact_excel_report(self, workbook, data):
        _logger.info("[CONTACT REPORT][EXCEL] Creating workbook with %s rows", len(data.get('rows', [])))
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#e9ecef',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
        })
        text_format = workbook.add_format({'border': 1})
        qty_format = workbook.add_format({'num_format': '#,##0.000', 'border': 1})
        money_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm', 'border': 1})

        worksheet = workbook.add_worksheet('Contact Transactions')
        row = 0
        worksheet.write(row, 0, 'Contact Transactions Report', header_format)
        row += 1
        worksheet.write(row, 0, 'Contact', header_format)
        worksheet.write(row, 1, data['partner'].display_name, text_format)
        row += 1
        worksheet.write(row, 0, 'Period', header_format)
        worksheet.write(row, 1, f"{data['date_from']} to {data['date_to']}", text_format)
        row += 2

        headers = [
            'Date', 'Contact', 'Product', 'Source App', 'Document', 'State',
            'Type', 'In', 'Out', 'Balance', 'Unit Price Incl VAT', 'Inventory Value',
            'Selling Price Incl VAT', 'Amount Incl VAT', 'VAT Amount', 'Location', 'Reference', 'Debug Source',
        ]
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1

        for report_row in data.get('rows', []):
            worksheet.write(row, 0, report_row['date'], date_format)
            worksheet.write(row, 1, report_row['contact'], text_format)
            worksheet.write(row, 2, report_row['product'], text_format)
            worksheet.write(row, 3, report_row['source_app'], text_format)
            worksheet.write(row, 4, report_row['source_document'], text_format)
            worksheet.write(row, 5, report_row['document_state'], text_format)
            worksheet.write(row, 6, report_row['transaction_type'], text_format)
            worksheet.write(row, 7, report_row['qty_in'] if report_row['qty_in'] else '', qty_format)
            worksheet.write(row, 8, report_row['qty_out'] if report_row['qty_out'] else '', qty_format)
            worksheet.write(row, 9, report_row['balance_qty'], qty_format)
            worksheet.write(row, 10, report_row['unit_price_incl_vat'], money_format)
            worksheet.write(row, 11, report_row['inventory_value'], money_format)
            worksheet.write(row, 12, report_row['selling_price_incl_vat'], money_format)
            worksheet.write(row, 13, report_row['amount_incl_vat'], money_format)
            worksheet.write(row, 14, report_row['vat_amount'], money_format)
            worksheet.write(row, 15, report_row['location'], text_format)
            worksheet.write(row, 16, report_row['reference'], text_format)
            worksheet.write(row, 17, report_row['debug_source'], text_format)
            row += 1

        worksheet.freeze_panes(5, 0)
        worksheet.autofilter(4, 0, max(row - 1, 4), len(headers) - 1)
        worksheet.set_column('A:A', 18)
        worksheet.set_column('B:C', 28)
        worksheet.set_column('D:G', 16)
        worksheet.set_column('H:M', 14)
        worksheet.set_column('N:R', 28)
