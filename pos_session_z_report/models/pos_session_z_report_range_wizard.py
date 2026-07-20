# -*- coding: utf-8 -*-
import base64
import calendar
import io
import logging
from datetime import datetime, time

import pytz
import xlsxwriter

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger('pos_session_z_report.range_wizard')
_TAG = '[ZReport][RangeWizard]'


class PosSessionZReportRangeWizard(models.TransientModel):
    _name = 'pos.session.z.report.range.wizard'
    _description = 'POS Session Z-Report Summary'

    period_type = fields.Selection(
        [
            ('month', 'Month'),
            ('quarter', 'Quarter'),
            ('ytd', 'Year to Date'),
            ('custom', 'Date Range'),
        ],
        string='Period',
        required=True,
        default='month',
    )
    year = fields.Integer(default=lambda self: fields.Date.context_today(self).year)
    month = fields.Selection(
        [(str(i), calendar.month_name[i]) for i in range(1, 13)],
        default=lambda self: str(fields.Date.context_today(self).month),
    )
    quarter = fields.Selection(
        [('1', 'Q1'), ('2', 'Q2'), ('3', 'Q3'), ('4', 'Q4')],
        default=lambda self: str(((fields.Date.context_today(self).month - 1) // 3) + 1),
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    config_ids = fields.Many2many('pos.config', string='Shops')
    include_in_progress = fields.Boolean(
        string='Include In-Progress Sessions',
        help='Include sessions that are not closed yet.',
    )
    report_file = fields.Binary(string='Download Z-Report Summary', readonly=True)
    report_filename = fields.Char(readonly=True)
    session_count = fields.Integer(readonly=True)
    state = fields.Selection(
        [('draft', 'Ready'), ('done', 'Generated')],
        default='draft',
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        date_from, date_to = self._compute_period_dates(
            vals.get('period_type') or 'month',
            int(vals.get('year') or fields.Date.context_today(self).year),
            int(vals.get('month') or fields.Date.context_today(self).month),
            int(vals.get('quarter') or ((fields.Date.context_today(self).month - 1) // 3) + 1),
        )
        vals.setdefault('date_from', date_from)
        vals.setdefault('date_to', date_to)
        _logger.debug('%s default_get values=%s', _TAG, vals)
        return vals

    @api.onchange('period_type', 'year', 'month', 'quarter')
    def _onchange_period(self):
        for wizard in self:
            if wizard.period_type == 'custom':
                continue
            date_from, date_to = wizard._compute_period_dates(
                wizard.period_type,
                wizard.year,
                int(wizard.month or 1),
                int(wizard.quarter or 1),
            )
            wizard.date_from = date_from
            wizard.date_to = date_to
            _logger.debug(
                '%s onchange period=%s year=%s month=%s quarter=%s -> %s..%s',
                _TAG, wizard.period_type, wizard.year, wizard.month, wizard.quarter,
                wizard.date_from, wizard.date_to,
            )

    def action_generate(self):
        self.ensure_one()
        self._validate_dates()

        sessions = self._find_sessions()
        _logger.info(
            '%s action_generate period=%s date_from=%s date_to=%s configs=%s include_open=%s sessions=%d ids=%s',
            _TAG,
            self.period_type,
            self.date_from,
            self.date_to,
            self.config_ids.mapped('name'),
            self.include_in_progress,
            len(sessions),
            sessions.ids,
        )

        if not sessions:
            raise UserError(_('No POS sessions found for the selected filters.'))

        summary = self._build_summary(sessions)
        xlsx_bytes = self._render_xlsx(sessions, summary)
        filename = self._build_filename()
        self.write({
            'report_file': base64.b64encode(xlsx_bytes),
            'report_filename': filename,
            'session_count': len(sessions),
            'state': 'done',
        })
        _logger.info('%s report written filename=%s bytes=%d', _TAG, filename, len(xlsx_bytes))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_print_pdf(self):
        self.ensure_one()
        self._validate_dates()
        _logger.info(
            '%s action_print_pdf wizard=%s period=%s date_from=%s date_to=%s configs=%s include_open=%s',
            _TAG,
            self.id,
            self.period_type,
            self.date_from,
            self.date_to,
            self.config_ids.mapped('name'),
            self.include_in_progress,
        )
        return self.env.ref(
            'pos_session_z_report.action_pos_session_z_report_range_pdf'
        ).report_action(self)

    def _validate_dates(self):
        if not self.date_from or not self.date_to:
            raise UserError(_('Please choose a date range.'))
        if self.date_from > self.date_to:
            raise UserError(_('Date From must be before Date To.'))

    def _find_sessions(self):
        start_dt, end_dt = self._local_date_range_to_utc()
        domain = [
            ('start_at', '>=', start_dt),
            ('start_at', '<=', end_dt),
        ]
        if self.config_ids:
            domain.append(('config_id', 'in', self.config_ids.ids))
        if not self.include_in_progress:
            domain.append(('state', '=', 'closed'))

        sessions = self.env['pos.session'].search(domain, order='start_at asc, id asc')
        _logger.debug('%s _find_sessions domain=%s -> %d', _TAG, domain, len(sessions))
        return sessions

    def _local_date_range_to_utc(self):
        tz_name = self.env.user.tz or self.env.context.get('tz') or 'UTC'
        tz = pytz.timezone(tz_name)
        local_start = tz.localize(datetime.combine(self.date_from, time.min))
        local_end = tz.localize(datetime.combine(self.date_to, time.max))
        utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_end = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
        _logger.debug(
            '%s local range %s..%s tz=%s -> utc %s..%s',
            _TAG, self.date_from, self.date_to, tz_name, utc_start, utc_end,
        )
        return utc_start, utc_end

    @api.model
    def _compute_period_dates(self, period_type, year, month, quarter):
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        quarter = int(quarter or ((today.month - 1) // 3) + 1)

        if period_type == 'quarter':
            start_month = ((quarter - 1) * 3) + 1
            end_month = start_month + 2
            return (
                fields.Date.to_date(datetime(year, start_month, 1)),
                fields.Date.to_date(datetime(year, end_month, calendar.monthrange(year, end_month)[1])),
            )
        if period_type == 'ytd':
            return fields.Date.to_date(datetime(year, 1, 1)), today
        return (
            fields.Date.to_date(datetime(year, month, 1)),
            fields.Date.to_date(datetime(year, month, calendar.monthrange(year, month)[1])),
        )

    def _build_summary(self, sessions):
        helper_model = self.env['pos.session.z.report.wizard']
        currency = sessions[:1].currency_id
        summary = {
            'currency': currency,
            'sales_total': 0.0,
            'transactions': 0,
            'profit_total': 0.0,
            'cost_total': 0.0,
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

        for session in sessions:
            helper = helper_model.create({'session_id': session.id})
            cash_row = helper._build_cash_row(session)
            other_rows = helper._build_noncash_rows(session)
            profit = helper._build_profit_data(session)
            activity = helper._build_activity_data(session)
            receipts = helper._build_receipts_data(session)

            total_sales = sum(session.order_ids.mapped('amount_total'))
            transactions = len(session.order_ids)
            noncash_total = sum(row['amount'] for row in other_rows)

            summary['sales_total'] += total_sales
            summary['transactions'] += transactions
            summary['profit_total'] += profit['total_profit']
            summary['cost_total'] += profit['total_cost']
            if cash_row:
                summary['cash_expected'] += cash_row['expected'] or 0.0
                summary['cash_counted'] += cash_row['counted'] or 0.0
                summary['cash_difference'] += cash_row['difference'] or 0.0
                for line_name, line_amount in cash_row['sub_lines']:
                    amount = line_amount or 0.0
                    if line_name == _('Cash Opening'):
                        summary['cash_opening'] += amount
                    elif str(line_name).startswith('Blind Audit Cash Out'):
                        summary['blind_audit_cashout'] += amount
                    elif line_name == _('COD Cash Collections'):
                        summary['cod_cash_collections'] += amount
                    elif line_name == session.name:
                        summary['pos_cash_sales'] += amount
            for row in other_rows:
                summary['noncash_by_method'][row['name'].replace(' %s' % session.name, '')] = (
                    summary['noncash_by_method'].get(row['name'].replace(' %s' % session.name, ''), 0.0)
                    + row['amount']
                )
            for receipt_key in ('deposit_rows', 'cod_rows', 'settle_rows'):
                for receipt in receipts[receipt_key]:
                    bucket = summary['receipts'][receipt_key].setdefault(
                        receipt['name'],
                        {'name': receipt['name'], 'amount': 0.0, 'count': 0},
                    )
                    bucket['amount'] += receipt['amount'] or 0.0
                    bucket['count'] += receipt['count'] or 0
            for metric in activity:
                bucket = summary['activity'].setdefault(metric['label'], {
                    'left_label': metric['left_label'],
                    'left_val': 0.0,
                    'right_label': metric['right_label'],
                    'right_val': 0.0,
                })
                bucket['left_val'] += metric['left_val'] or 0.0
                bucket['right_val'] += metric['right_val'] or 0.0

            summary['sessions'].append({
                'name': session.name,
                'shop': session.config_id.name,
                'opened_by': session.user_id.name,
                'start_at': session.start_at,
                'stop_at': session.stop_at,
                'state': session.state,
                'transactions': transactions,
                'sales_total': total_sales,
                'cash_expected': cash_row['expected'] if cash_row else 0.0,
                'cash_counted': cash_row['counted'] if cash_row else 0.0,
                'cash_difference': cash_row['difference'] if cash_row else 0.0,
                'noncash_total': noncash_total,
                'profit_total': profit['total_profit'],
                'margin_pct': profit['margin_pct'],
            })
            _logger.debug(
                '%s session=%s sales=%.2f tx=%d cash_diff=%.2f noncash=%.2f profit=%.2f',
                _TAG,
                session.name,
                total_sales,
                transactions,
                summary['sessions'][-1]['cash_difference'],
                noncash_total,
                profit['total_profit'],
            )

        summary['margin_pct'] = (
            (summary['profit_total'] / summary['sales_total']) * 100.0
            if summary['sales_total'] else 0.0
        )
        _logger.info(
            '%s totals sessions=%d sales=%.2f tx=%d profit=%.2f margin=%.2f cash_open=%.2f blind_out=%.2f cod_cash=%.2f pos_cash=%.2f cash_diff=%.2f',
            _TAG,
            len(sessions),
            summary['sales_total'],
            summary['transactions'],
            summary['profit_total'],
            summary['margin_pct'],
            summary['cash_opening'],
            summary['blind_audit_cashout'],
            summary['cod_cash_collections'],
            summary['pos_cash_sales'],
            summary['cash_difference'],
        )
        return summary

    def _render_xlsx(self, sessions, summary):
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        formats = self._make_formats(wb)
        self._render_summary_sheet(wb, formats, sessions, summary)
        self._render_receipts_sheet(wb, formats, summary)
        self._render_sessions_sheet(wb, formats, summary)
        wb.close()
        output.seek(0)
        return output.read()

    def _make_formats(self, wb):
        return {
            'title': wb.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'font_color': 'white', 'bg_color': '#24364d'}),
            'section': wb.add_format({'bold': True, 'bg_color': '#d9eaf7', 'border': 1}),
            'th': wb.add_format({'bold': True, 'font_color': 'white', 'bg_color': '#4774ad', 'border': 1}),
            'label': wb.add_format({'bold': True, 'border': 1}),
            'cell': wb.add_format({'border': 1}),
            'money': wb.add_format({'num_format': '#,##0.00', 'border': 1}),
            'money_bold': wb.add_format({'bold': True, 'num_format': '#,##0.00', 'border': 1}),
            'pct': wb.add_format({'num_format': '0.00%', 'border': 1}),
            'date': wb.add_format({'num_format': 'dd/mm/yyyy hh:mm', 'border': 1}),
            'diff_pos': wb.add_format({'num_format': '#,##0.00', 'font_color': 'green', 'bold': True, 'border': 1}),
            'diff_neg': wb.add_format({'num_format': '#,##0.00', 'font_color': 'red', 'bold': True, 'border': 1}),
        }

    def _render_summary_sheet(self, wb, f, sessions, summary):
        ws = wb.add_worksheet('Z-Report Summary')
        ws.set_column('A:A', 30)
        ws.set_column('B:D', 20)
        row = 0
        ws.merge_range(row, 0, row, 3, 'Z - REPORT SUMMARY', f['title'])
        row += 2

        period_label = self._period_label()
        info_rows = [
            ('Period', period_label),
            ('Date From', str(self.date_from)),
            ('Date To', str(self.date_to)),
            ('Shops', ', '.join(self.config_ids.mapped('name')) if self.config_ids else 'All'),
            ('Include In-Progress', 'Yes' if self.include_in_progress else 'No'),
            ('Sessions', len(sessions)),
        ]
        for label, value in info_rows:
            ws.write(row, 0, label, f['label'])
            ws.write(row, 1, value, f['cell'])
            row += 1

        row += 1
        ws.merge_range(row, 0, row, 3, 'Totals', f['section'])
        row += 1
        totals = [
            ('Total Sales', summary['sales_total']),
            ('Transactions', summary['transactions']),
            ('Total Cost', summary['cost_total']),
            ('Total Profit', summary['profit_total']),
            ('Profit Margin', summary['margin_pct'] / 100.0),
            ('Cash Expected', summary['cash_expected']),
            ('Cash Counted', summary['cash_counted']),
            ('Cash Difference', summary['cash_difference']),
        ]
        for label, value in totals:
            ws.write(row, 0, label, f['label'])
            if label == 'Profit Margin':
                ws.write(row, 1, value, f['pct'])
            elif label == 'Transactions':
                ws.write(row, 1, value, f['cell'])
            elif label == 'Cash Difference':
                ws.write(row, 1, value, f['diff_pos'] if value >= 0 else f['diff_neg'])
            else:
                ws.write(row, 1, value, f['money_bold'])
            row += 1

        row += 1
        ws.merge_range(row, 0, row, 3, 'Session Control Cash Movement Sums', f['section'])
        row += 1
        for col, label in enumerate(['Cash Opening', 'Blind Audit Cash Out', 'COD Cash Collections', 'POS Cash Sales']):
            ws.write(row, col, label, f['th'])
        row += 1
        ws.write(row, 0, summary['cash_opening'], f['money_bold'])
        ws.write(row, 1, summary['blind_audit_cashout'], f['money_bold'])
        ws.write(row, 2, summary['cod_cash_collections'], f['money_bold'])
        ws.write(row, 3, summary['pos_cash_sales'], f['money_bold'])
        row += 1

        row += 1
        ws.merge_range(row, 0, row, 3, 'Other Payment Methods', f['section'])
        row += 1
        ws.write(row, 0, 'Payment Method', f['th'])
        ws.write(row, 1, 'Amount', f['th'])
        row += 1
        for method, amount in sorted(summary['noncash_by_method'].items()):
            ws.write(row, 0, method, f['cell'])
            ws.write(row, 1, amount, f['money'])
            row += 1

        row += 1
        ws.merge_range(row, 0, row, 3, 'Session Activity Summary', f['section'])
        row += 1
        for col, label in enumerate(['Metric', 'Created / Issued / Reg.', 'Amount', 'Used / Redeemed / Rec.', 'Amount']):
            ws.write(row, col, label, f['th'])
        row += 1
        for label, metric in summary['activity'].items():
            ws.write(row, 0, label, f['label'])
            ws.write(row, 1, metric['left_label'], f['cell'])
            ws.write(row, 2, metric['left_val'], f['money'])
            ws.write(row, 3, metric['right_label'], f['cell'])
            ws.write(row, 4, metric['right_val'], f['money'])
            row += 1

    def _render_receipts_sheet(self, wb, f, summary):
        ws = wb.add_worksheet('Receipts Detail')
        ws.set_column('A:A', 34)
        ws.set_column('B:B', 16)
        ws.set_column('C:D', 18)

        row = 0
        ws.merge_range(row, 0, row, 3, 'RECEIPTS DETAIL SUMMARY', f['title'])
        row += 2

        sections = [
            ('Customer Account Deposits', summary['receipts']['deposit_rows']),
            ('COD Order Payments', summary['receipts']['cod_rows']),
            ('Payments for Settle Due Accounts', summary['receipts']['settle_rows']),
        ]
        for title, rows_by_method in sections:
            ws.merge_range(row, 0, row, 3, title, f['section'])
            row += 1
            for col, label in enumerate(['Payment Method', 'Transactions', 'Amount', 'Currency']):
                ws.write(row, col, label, f['th'])
            row += 1

            total_count = 0
            total_amount = 0.0
            rows = sorted(rows_by_method.values(), key=lambda data: data['name'])
            if not rows:
                ws.merge_range(row, 0, row, 3, 'No payments recorded in this period.', f['cell'])
                row += 1
            for data in rows:
                ws.write(row, 0, data['name'], f['cell'])
                ws.write(row, 1, data['count'], f['cell'])
                ws.write(row, 2, data['amount'], f['money'])
                ws.write(row, 3, summary['currency'].symbol or '', f['cell'])
                total_count += data['count']
                total_amount += data['amount']
                row += 1
            ws.write(row, 0, 'TOTAL', f['label'])
            ws.write(row, 1, total_count, f['label'])
            ws.write(row, 2, total_amount, f['money_bold'])
            ws.write(row, 3, summary['currency'].symbol or '', f['label'])
            row += 2

    def _render_sessions_sheet(self, wb, f, summary):
        ws = wb.add_worksheet('Sessions')
        widths = [16, 18, 20, 18, 18, 14, 12, 14, 14, 14, 14, 14, 14, 12]
        for col, width in enumerate(widths):
            ws.set_column(col, col, width)

        headers = [
            'Session', 'Shop', 'Opened By', 'Opening Date', 'Closing Date', 'Status',
            'Transactions', 'Sales', 'Cash Expected', 'Cash Counted', 'Cash Difference',
            'Other Payments', 'Profit', 'Margin %',
        ]
        for col, label in enumerate(headers):
            ws.write(0, col, label, f['th'])

        for row, data in enumerate(summary['sessions'], start=1):
            ws.write(row, 0, data['name'], f['cell'])
            ws.write(row, 1, data['shop'], f['cell'])
            ws.write(row, 2, data['opened_by'], f['cell'])
            ws.write_datetime(row, 3, data['start_at'], f['date']) if data['start_at'] else ws.write(row, 3, '', f['cell'])
            ws.write_datetime(row, 4, data['stop_at'], f['date']) if data['stop_at'] else ws.write(row, 4, '', f['cell'])
            ws.write(row, 5, data['state'], f['cell'])
            ws.write(row, 6, data['transactions'], f['cell'])
            ws.write(row, 7, data['sales_total'], f['money'])
            ws.write(row, 8, data['cash_expected'], f['money'])
            ws.write(row, 9, data['cash_counted'], f['money'])
            ws.write(row, 10, data['cash_difference'], f['diff_pos'] if data['cash_difference'] >= 0 else f['diff_neg'])
            ws.write(row, 11, data['noncash_total'], f['money'])
            ws.write(row, 12, data['profit_total'], f['money'])
            ws.write(row, 13, data['margin_pct'] / 100.0, f['pct'])

    def _period_label(self):
        if self.period_type == 'month':
            return '%s %s' % (calendar.month_name[int(self.month)], self.year)
        if self.period_type == 'quarter':
            return 'Q%s %s' % (self.quarter, self.year)
        if self.period_type == 'ytd':
            return 'Year to Date %s' % self.year
        return 'Date Range'

    def _build_filename(self):
        safe_period = self._period_label().replace(' ', '_').replace('/', '-')
        return 'Z-Report_Summary_%s__%s_to_%s.xlsx' % (
            safe_period,
            self.date_from,
            self.date_to,
        )
