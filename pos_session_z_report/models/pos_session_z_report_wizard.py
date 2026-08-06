# -*- coding: utf-8 -*-
import io
import base64
import logging

import xlsxwriter

from odoo import models, fields, _

_logger = logging.getLogger('pos_session_z_report.wizard')
_TAG = '[ZReport][Wizard]'


class PosSessionZReportWizard(models.TransientModel):
    _name = 'pos.session.z.report.wizard'
    _description = 'POS Session Z-Report'

    session_id = fields.Many2one(
        'pos.session',
        string='Session',
        required=True,
        default=lambda self: self._default_session(),
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='session_id.currency_id',
        readonly=True,
    )
    report_file = fields.Binary(string='Download Z-Report', readonly=True)
    report_filename = fields.Char(readonly=True)
    state = fields.Selection(
        [('draft', 'Ready'), ('done', 'Generated')],
        default='draft',
    )

    def _default_session(self):
        ctx = self.env.context
        return ctx.get('default_session_id') or ctx.get('active_id')

    # ── Main entry point ─────────────────────────────────────────────────────

    def action_generate(self):
        self.ensure_one()
        session = self.session_id
        sym = session.currency_id.symbol or ''

        _logger.info('%s action_generate — session=%s id=%s', _TAG, session.name, session.id)

        cash_row     = self._build_cash_row(session)
        other_rows   = self._build_noncash_rows(session)
        profit       = self._build_profit_data(session)
        activity     = self._build_activity_data(session)
        receipts     = self._build_receipts_data(session)

        _logger.info(
            '%s data ready — cash=%s  other_rows=%d  activity=%d  receipts: deposit=%d cod=%d settle=%d',
            _TAG,
            bool(cash_row),
            len(other_rows),
            len(activity),
            len(receipts['deposit_rows']),
            len(receipts['cod_rows']),
            len(receipts['settle_rows']),
        )

        xlsx_bytes = self._render_xlsx(session, sym, cash_row, other_rows, profit, activity, receipts)
        filename = 'Z-Report_{}__{}.xlsx'.format(
            session.name.replace('/', '-'),
            fields.Date.today(),
        )
        self.write({
            'report_file':     base64.b64encode(xlsx_bytes),
            'report_filename': filename,
            'state':           'done',
        })
        _logger.info('%s report written — filename=%s', _TAG, filename)
        return {
            'type':      'ir.actions.act_window',
            'res_model': self._name,
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    def action_print_pdf(self):
        self.ensure_one()
        _logger.info('%s action_print_pdf — wizard=%s session=%s',
                     _TAG, self.id, self.session_id.name)
        return self.env.ref(
            'pos_session_z_report.action_pos_session_z_report_pdf'
        ).report_action(self)

    # ── Sheet 1 data helpers ──────────────────────────────────────────────────

    def _build_cash_row(self, session):
        """Cash drawer row with sub-lines (opening, blind-audit, COD, sales)."""
        cash_method = session.payment_method_ids.filtered('is_cash_count')[:1]
        if not cash_method:
            _logger.info('%s _build_cash_row — no cash method found', _TAG)
            return None

        all_payments = session.order_ids.mapped('payment_ids')
        cash_total = sum(
            all_payments
            .filtered(lambda p: p.payment_method_id == cash_method)
            .mapped('amount')
        )
        _logger.debug(
            '%s _build_cash_row — method="%s"  cash_total=%.2f',
            _TAG, cash_method.name, cash_total,
        )

        sub_lines = [(_('Cash Opening'), session.cash_register_balance_start)]

        if 'blind_cash_out' in session._fields and session.blind_cash_out:
            sub_lines.append((
                'Blind Audit Cash Out - {}'.format(session.name),
                -abs(session.blind_cash_out),
            ))

        if 'pos.cod.collection' in self.env:
            cod_cash = session._cod_cash_collection_total()
            if cod_cash:
                sub_lines.append((_('COD Cash Collections'), cod_cash))
                _logger.debug('%s _build_cash_row — COD cash=%.2f', _TAG, cod_cash)

        sub_lines.append((session.name, cash_total))

        float_carry_fwd = None
        if 'blind_cash_balance' in session._fields:
            float_carry_fwd = session.blind_cash_balance
            _logger.debug('%s _build_cash_row — float_carry_fwd=%.2f', _TAG, float_carry_fwd)

        return {
            'name':             '{} {}'.format(cash_method.name, session.name),
            'expected':         session.cash_register_balance_end,
            'counted':          session.cash_register_balance_end_real,
            'difference':       session.cash_register_difference,
            'sub_lines':        sub_lines,
            'float_carry_fwd':  float_carry_fwd,
        }

    def _build_noncash_rows(self, session):
        """One row per non-cash-drawer payment method that has transactions."""
        all_payments = session.order_ids.mapped('payment_ids')
        cash_method  = session.payment_method_ids.filtered('is_cash_count')[:1]

        # Configured non-drawer methods + any unconfigured methods present in payments
        configured = session.payment_method_ids.filtered(lambda m: m != cash_method)
        extra = all_payments.mapped('payment_method_id').filtered(
            lambda m: m not in session.payment_method_ids and m != cash_method
        )

        rows = []
        for method in configured | extra:
            amount = sum(
                all_payments
                .filtered(lambda p: p.payment_method_id == method)
                .mapped('amount')
            )
            if not amount:
                continue
            _logger.debug(
                '%s _build_noncash_rows — method="%s"  amount=%.2f',
                _TAG, method.name, amount,
            )
            rows.append({
                'name':   '{} {}'.format(method.name, session.name),
                'amount': amount,
            })

        _logger.info('%s _build_noncash_rows — %d row(s)', _TAG, len(rows))
        return rows

    def _build_profit_data(self, session):
        return {
            'total_selling': session.session_total_selling_price,
            'total_cost':    session.session_total_cost_incl_vat,
            'total_profit':  session.session_total_profit,
            'margin_pct':    session.session_profit_margin_pct,
        }

    # ── XLSX renderer ─────────────────────────────────────────────────────────

    def _render_xlsx(self, session, sym, cash_row, other_rows, profit, activity, receipts):
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        F = self._make_formats(wb)

        self._render_z_report_sheet(wb, F, session, sym, cash_row, other_rows, profit, activity)
        self._render_receipts_sheet(wb, F, session, sym, receipts)

        wb.close()
        output.seek(0)
        return output.read()

    # ── Sheet 1: Z-Report ────────────────────────────────────────────────────

    def _render_z_report_sheet(self, wb, F, session, sym, cash_row, other_rows, profit, activity):
        ws = wb.add_worksheet('Z-Report')
        ws.set_column('A:A', 50)
        ws.set_column('B:D', 22)
        r = 0

        ws.set_row(r, 30)
        ws.merge_range(r, 0, r, 3, 'Z - REPORT', F['title'])
        r += 1

        close_dt = session.stop_at.strftime('%d/%m/%Y %H:%M') if session.stop_at else '-'
        ws.write(r, 0, 'Shop:',    F['bold']); ws.write(r, 1, session.config_id.name)
        ws.write(r, 2, 'Date:',    F['bold']); ws.write(r, 3, close_dt)
        r += 1
        ws.write(r, 0, 'Session:', F['bold']); ws.write(r, 1, session.name)
        ws.write(r, 2, 'Cashier:', F['bold']); ws.write(r, 3, session.user_id.name)
        r += 2

        total_sales = sum(session.order_ids.mapped('amount_total'))
        num_tx = len(session.order_ids)
        ws.merge_range(r, 0, r, 3, 'Session Control', F['section']); r += 1
        ws.write(r, 0, 'Total:', F['bold'])
        ws.write(r, 1, total_sales, F['money_bold'])
        ws.write(r, 2, sym); r += 1
        ws.write(r, 0, 'Number of transactions:', F['bold'])
        ws.write(r, 1, num_tx); r += 2

        for col, label in enumerate(['Name', 'Expected', 'Counted', 'Difference']):
            ws.write(r, col, label, F['th'])
        r += 1

        if cash_row:
            ws.write(r, 0, cash_row['name'],     F['bold'])
            ws.write(r, 1, cash_row['expected'],  F['money_bold'])
            ws.write(r, 2, cash_row['counted'],   F['money_bold'])
            diff = cash_row['difference']
            ws.write(r, 3, diff, F['diff_pos'] if diff >= 0 else F['diff_neg'])
            r += 1
            for sl_name, sl_amount in cash_row['sub_lines']:
                ws.write(r, 0, sl_name,   F['sub_label'])
                ws.write(r, 1, sl_amount, F['sub_money'])
                r += 1

        r += 1

        if other_rows:
            ws.merge_range(r, 0, r, 3, 'Other Payment Methods', F['section']); r += 1
            for col, label in enumerate(['Name', 'Amount', '', '']):
                ws.write(r, col, label, F['th'])
            r += 1
            for pm in other_rows:
                ws.write(r, 0, pm['name'],   F['bold'])
                ws.write(r, 1, pm['amount'], F['money_bold'])
                r += 1
            r += 1

        ws.merge_range(r, 0, r, 3, 'Session Profit Summary', F['section']); r += 1
        for col, label in enumerate(['Revenue & Cost', '', 'Profit', '']):
            ws.write(r, col, label, F['th'])
        r += 1
        ws.write(r, 0, 'Total Selling Price',                  F['bold'])
        ws.write(r, 1, profit['total_selling'],                 F['money'])
        ws.write(r, 2, 'Total Profit',                          F['bold'])
        ws.write(r, 3, profit['total_profit'],                  F['profit'])
        r += 1
        ws.write(r, 0, 'Total Cost (incl. VAT + Landed Costs)', F['bold'])
        ws.write(r, 1, profit['total_cost'],                    F['money'])
        ws.write(r, 2, 'Profit Margin (%)',                     F['bold'])
        ws.write(r, 3, '{:.2f}%'.format(profit['margin_pct']))
        r += 2

        notes = [
            u'• Cost per unit = Standard Price \xd7 (1 + VAT%). Standard Price reflects AVCO/landed costs.',
            u'• Selling Price = sum of line unit prices \xd7 quantities (before session-level discounts).',
            u'• Values computed from order data at report generation time.',
        ]
        ws.write(r, 0, 'Notes:', wb.add_format({'bold': True, 'font_size': 8})); r += 1
        for note in notes:
            ws.merge_range(r, 0, r, 3, note, F['note']); r += 1

        r += 1
        r = self._render_activity_section(ws, wb, F, r, sym, activity)

    # ── Sheet 1 sub-renderer: Session Activity Summary ───────────────────────

    def _render_activity_section(self, ws, wb, F, r, sym, activity):
        """Render the Session Activity Summary table on the Z-Report sheet.

        Columns: Metric | Created/Issued | Note | Used/Redeemed | Note
        Two numeric columns (B=left_val, D=right_val) with italic notes in C and E.
        """
        ws.set_column('A:A', 42)
        ws.set_column('B:B', 18)
        ws.set_column('C:C', 22)
        ws.set_column('D:D', 18)

        # Section title
        ws.merge_range(r, 0, r, 3, 'Session Activity Summary', F['section_activity']); r += 1

        # Column headers
        for col, lbl in enumerate(['Metric', 'Created / Issued / Reg.', 'Details', 'Used / Redeemed / Rec.']):
            ws.write(r, col, lbl, F['th'])
        r += 1

        if not activity:
            ws.merge_range(r, 0, r, 3, 'No activity data available.', F['note']); r += 1
            return r

        note_fmt = wb.add_format({
            'italic': True, 'font_size': 9, 'font_color': '#555555', 'align': 'left',
        })

        for m in activity:
            ws.write(r, 0, m['label'],       F['bold'])
            ws.write(r, 1, m['left_val'],    F['money_bold'])
            ws.write(r, 2, m['left_note'],   note_fmt)
            ws.write(r, 3, m['right_val'],   F['activity_right'])
            # squeeze right_note + right_label together into col 3 tooltip via next row
            # write right_label as sub-label under the right amount
            r += 1
            # sub-row: blank | left_label (italic) | blank | right_label (italic)
            ws.write(r, 0, '',                F['sub_label'])
            ws.write(r, 1, m['left_label'],   F['sub_label'])
            ws.write(r, 2, '',                F['sub_label'])
            ws.write(r, 3, f"{m['right_label']}  {m['right_note']}", F['sub_label'])
            r += 1

        # Footer note
        r += 1
        footer_fmt = wb.add_format({'italic': True, 'font_size': 8, 'font_color': '#888888'})
        ws.merge_range(r, 0, r, 3,
            u'• Activity data computed at report generation time from live session records.',
            footer_fmt)
        r += 1
        ws.merge_range(r, 0, r, 3,
            u'• Deposit/settle split uses partner credit balance at report time.',
            footer_fmt)
        r += 1
        return r

    # ── Sheet 2: Receipts Detail ──────────────────────────────────────────────

    def _render_receipts_sheet(self, wb, F, session, sym, receipts):
        ws = wb.add_worksheet('Receipts Detail')
        ws.set_column('A:A', 42)
        ws.set_column('B:B', 18)
        ws.set_column('C:C', 18)
        ws.set_column('D:D', 18)
        r = 0

        _logger.info('%s _render_receipts_sheet — session=%s', _TAG, session.name)

        # Title
        ws.set_row(r, 30)
        ws.merge_range(r, 0, r, 3, 'RECEIPTS DETAIL', F['title']); r += 1

        # Session header
        close_dt = session.stop_at.strftime('%d/%m/%Y %H:%M') if session.stop_at else '-'
        ws.write(r, 0, 'Shop:',    F['bold']); ws.write(r, 1, session.config_id.name)
        ws.write(r, 2, 'Date:',    F['bold']); ws.write(r, 3, close_dt); r += 1
        ws.write(r, 0, 'Session:', F['bold']); ws.write(r, 1, session.name)
        ws.write(r, 2, 'Cashier:', F['bold']); ws.write(r, 3, session.user_id.name)
        r += 2

        # ── Section 1: Customer Account Deposits ──────────────────────────────
        r = self._render_receipts_section(
            ws, wb, F, r, sym,
            title='CUSTOMER ACCOUNT DEPOSITS',
            subtitle=(
                'Advance payments received from customers to pre-load '
                'their account balance (no outstanding dues at time of payment).'
            ),
            rows=receipts['deposit_rows'],
            empty_msg='No customer deposit payments recorded in this session.',
        )
        r += 1

        # ── Section 2: COD Order Payments ─────────────────────────────────────
        r = self._render_receipts_section(
            ws, wb, F, r, sym,
            title='COD ORDER PAYMENTS',
            subtitle=(
                'Cash-on-delivery collections received during this session '
                'for dispatched COD orders.'
            ),
            rows=receipts['cod_rows'],
            empty_msg='No COD order payments recorded in this session.',
        )
        r += 1

        # ── Section 3: Payments for Settle Due Accounts ───────────────────────
        r = self._render_receipts_section(
            ws, wb, F, r, sym,
            title='PAYMENTS FOR SETTLE DUE ACCOUNTS',
            subtitle=(
                'Payments received from customers to settle their outstanding '
                'account balances (credit / due amount).'
            ),
            rows=receipts['settle_rows'],
            empty_msg='No account settlement payments recorded in this session.',
        )

        # Footer note
        r += 2
        note_fmt = wb.add_format({'italic': True, 'font_size': 8, 'font_color': '#888888'})
        ws.merge_range(
            r, 0, r, 3,
            u'• Deposit / Settle split is based on partner account balance at report generation time.',
            note_fmt,
        )
        r += 1
        ws.merge_range(
            r, 0, r, 3,
            u'• COD payments sourced from pos.cod.collection records for this session.',
            note_fmt,
        )

    def _render_receipts_section(self, ws, wb, F, r, sym,
                                  title, subtitle, rows, empty_msg):
        """Render one titled section on the Receipts Detail sheet.

        Layout:
            [section title bar]
            [italic subtitle]
            [column headers: Payment Method | Transactions | Amount | Currency]
            [data rows...]
            [total row]

        Returns the next available row index.
        """
        # Section title
        ws.merge_range(r, 0, r, 3, title, F['section_receipts']); r += 1

        # Subtitle
        subtitle_fmt = wb.add_format({
            'italic': True, 'font_size': 9, 'font_color': '#444444',
        })
        ws.merge_range(r, 0, r, 3, subtitle, subtitle_fmt); r += 1

        # Column headers
        for col, label in enumerate(['Payment Method', 'Transactions', 'Amount', '']):
            ws.write(r, col, label, F['th'])
        r += 1

        if not rows:
            empty_fmt = wb.add_format({'italic': True, 'font_color': '#888888'})
            ws.merge_range(r, 0, r, 3, empty_msg, empty_fmt); r += 1
            _logger.info('%s section "%s" — no data rows', _TAG, title)
            return r

        total_amount = 0.0
        total_count  = 0
        for row in rows:
            ws.write(r, 0, row['name'],   F['bold'])
            ws.write(r, 1, row['count'],  F['center'])
            ws.write(r, 2, row['amount'], F['money_bold'])
            ws.write(r, 3, sym)
            total_amount += row['amount']
            total_count  += row['count']
            _logger.debug(
                '%s section "%s" — method="%s" count=%d amount=%.2f',
                _TAG, title, row['name'], row['count'], row['amount'],
            )
            r += 1

        # Total row
        ws.write(r, 0, 'TOTAL', F['total_label'])
        ws.write(r, 1, total_count,  F['total_center'])
        ws.write(r, 2, total_amount, F['total_money'])
        ws.write(r, 3, sym,          F['total_label'])
        r += 1

        _logger.info(
            '%s section "%s" — %d method(s)  total_count=%d  total_amount=%.2f',
            _TAG, title, len(rows), total_count, total_amount,
        )
        return r

    # ── Format factory ────────────────────────────────────────────────────────

    def _make_formats(self, wb):
        num_fmt = '#,##0.00'

        def f(opts):
            return wb.add_format(opts)

        return {
            'title':           f({'bold': True, 'font_size': 16,
                                  'align': 'center', 'valign': 'vcenter',
                                  'bg_color': '#2E4057', 'font_color': '#FFFFFF'}),
            'section':          f({'bold': True, 'font_size': 11,
                                   'bg_color': '#D6E4F0', 'border': 1}),
            'section_receipts': f({'bold': True, 'font_size': 11,
                                   'bg_color': '#D5E8D4', 'border': 1,
                                   'font_color': '#1A5E1A'}),
            'section_activity': f({'bold': True, 'font_size': 11,
                                   'bg_color': '#FFF2CC', 'border': 1,
                                   'font_color': '#7D4D00'}),
            'activity_right':   f({'bold': True, 'num_format': '#,##0.00',
                                   'align': 'right', 'font_color': '#1F497D'}),
            'th':              f({'bold': True, 'bg_color': '#4A6FA5',
                                  'font_color': '#FFFFFF', 'border': 1,
                                  'align': 'center'}),
            'bold':            f({'bold': True}),
            'center':          f({'align': 'center'}),
            'money':           f({'num_format': num_fmt, 'align': 'right'}),
            'money_bold':      f({'bold': True, 'num_format': num_fmt,
                                  'align': 'right'}),
            'profit':          f({'bold': True, 'num_format': num_fmt,
                                  'align': 'right', 'font_color': '#1A7F3C'}),
            'diff_pos':        f({'num_format': num_fmt, 'align': 'right',
                                  'font_color': '#1A7F3C'}),
            'diff_neg':        f({'num_format': num_fmt, 'align': 'right',
                                  'font_color': '#C0392B'}),
            'sub_label':       f({'indent': 2, 'italic': True,
                                  'font_color': '#555555'}),
            'sub_money':       f({'indent': 2, 'italic': True,
                                  'num_format': num_fmt, 'align': 'right',
                                  'font_color': '#555555'}),
            'total_label':     f({'bold': True, 'bg_color': '#E8F4E8',
                                  'border': 1}),
            'total_center':    f({'bold': True, 'bg_color': '#E8F4E8',
                                  'border': 1, 'align': 'center'}),
            'total_money':     f({'bold': True, 'bg_color': '#E8F4E8',
                                  'border': 1, 'num_format': num_fmt,
                                  'align': 'right', 'font_color': '#1A5E1A'}),
            'note':            f({'italic': True, 'font_size': 8,
                                  'font_color': '#888888'}),
        }
