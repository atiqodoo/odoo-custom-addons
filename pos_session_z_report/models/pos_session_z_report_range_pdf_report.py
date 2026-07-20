# -*- coding: utf-8 -*-
import logging

import pytz

from odoo import models


_logger = logging.getLogger('pos_session_z_report.range_pdf')
_TAG = '[ZReport][RangePDF]'
_EAT = pytz.timezone('Africa/Nairobi')


def _to_eat(dt):
    if not dt:
        return '-'
    return pytz.utc.localize(dt).astimezone(_EAT).strftime('%d/%m/%Y %H:%M')


class PosSessionZReportRangePdfReport(models.AbstractModel):
    _name = 'report.pos_session_z_report.pos_session_z_report_range_pdf'
    _description = 'Z-Report Summary PDF Data Provider'

    def _get_report_values(self, docids, data=None):
        wizards = self.env['pos.session.z.report.range.wizard'].browse(docids)
        docs = []
        for wizard in wizards:
            sessions = wizard._find_sessions()
            summary = wizard._build_summary(sessions) if sessions else {
                'sales_total': 0.0,
                'transactions': 0,
                'cost_total': 0.0,
                'profit_total': 0.0,
                'margin_pct': 0.0,
                'cash_expected': 0.0,
                'cash_counted': 0.0,
                'cash_difference': 0.0,
                'cash_opening': 0.0,
                'blind_audit_cashout': 0.0,
                'cod_cash_collections': 0.0,
                'pos_cash_sales': 0.0,
                'noncash_by_method': {},
                'activity': {},
                'receipts': {
                    'deposit_rows': {},
                    'cod_rows': {},
                    'settle_rows': {},
                },
                'sessions': [],
            }
            sym = sessions[:1].currency_id.symbol if sessions else ''
            period_label = wizard._period_label()

            _logger.info(
                '%s build wizard=%s period=%s date_from=%s date_to=%s sessions=%d ids=%s',
                _TAG,
                wizard.id,
                period_label,
                wizard.date_from,
                wizard.date_to,
                len(sessions),
                sessions.ids,
            )

            receipt_sections = [
                {
                    'title': 'Customer Account Deposits',
                    'subtitle': 'Advance payments received from customers to pre-load their account balance.',
                    'rows': sorted(summary['receipts']['deposit_rows'].values(), key=lambda row: row['name']),
                    'empty': 'No customer deposit payments recorded in this period.',
                },
                {
                    'title': 'COD Order Payments',
                    'subtitle': 'Cash-on-delivery collections received for dispatched COD orders.',
                    'rows': sorted(summary['receipts']['cod_rows'].values(), key=lambda row: row['name']),
                    'empty': 'No COD order payments recorded in this period.',
                },
                {
                    'title': 'Payments for Settle Due Accounts',
                    'subtitle': 'Payments received from customers to settle outstanding account balances.',
                    'rows': sorted(summary['receipts']['settle_rows'].values(), key=lambda row: row['name']),
                    'empty': 'No account settlement payments recorded in this period.',
                },
            ]
            for section in receipt_sections:
                section['total_count'] = sum(row['count'] for row in section['rows'])
                section['total_amount'] = sum(row['amount'] for row in section['rows'])

            docs.append({
                'wizard': wizard,
                'period_label': period_label,
                'sessions': sessions,
                'summary': summary,
                'sym': sym or '',
                'noncash_rows': sorted(summary['noncash_by_method'].items()),
                'activity_rows': list(summary['activity'].items()),
                'receipt_sections': receipt_sections,
                'session_rows': [
                    dict(row, start_eat=_to_eat(row.get('start_at')), stop_eat=_to_eat(row.get('stop_at')))
                    for row in summary['sessions']
                ],
            })

        _logger.info('%s built %d doc(s)', _TAG, len(docs))
        return {'docs': docs}
