# -*- coding: utf-8 -*-
import logging
import pytz
from odoo import models

_logger = logging.getLogger('pos_session_z_report.pdf_report')
_TAG = '[ZReport][PDF]'

_EAT = pytz.timezone('Africa/Nairobi')   # UTC+3, covers Mombasa/Nairobi


def _to_eat(dt):
    """Convert a UTC naive datetime (as stored by Odoo) to EAT formatted string."""
    if not dt:
        return '-'
    utc_dt = pytz.utc.localize(dt)
    return utc_dt.astimezone(_EAT).strftime('%d/%m/%Y %H:%M')


class PosSessionZReportPdfReport(models.AbstractModel):
    _name = 'report.pos_session_z_report.pos_session_z_report_pdf'
    _description = 'Z-Report PDF Data Provider'

    def _get_report_values(self, docids, data=None):
        """Build all section data for each wizard record and return to QWeb."""
        wizards = self.env['pos.session.z.report.wizard'].browse(docids)
        docs = []
        for wizard in wizards:
            session = wizard.session_id
            _logger.info('%s _get_report_values — wizard=%s session=%s',
                         _TAG, wizard.id, session.name)

            opened_at = _to_eat(session.start_at)
            closed_at = _to_eat(session.stop_at) if session.stop_at else 'In Progress'

            _logger.info('%s session times EAT — opened=%s  closed=%s',
                         _TAG, opened_at, closed_at)

            sym        = session.currency_id.symbol or ''
            cash_row   = wizard._build_cash_row(session)
            other_rows = wizard._build_noncash_rows(session)
            profit     = wizard._build_profit_data(session)
            activity   = wizard._build_activity_data(session)
            receipts   = wizard._build_receipts_data(session)

            docs.append({
                'wizard':     wizard,
                'session':    session,
                'sym':        sym,
                'opened_at':  opened_at,
                'closed_at':  closed_at,
                'cash_row':   cash_row,
                'other_rows': other_rows,
                'profit':     profit,
                'activity':   activity,
                'receipts':   receipts,
            })

        _logger.info('%s _get_report_values — built %d doc(s)', _TAG, len(docs))
        return {'docs': docs}
