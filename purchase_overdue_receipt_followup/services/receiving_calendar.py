from datetime import timedelta

from pytz import UTC

from odoo import models


class PurchaseReceivingCalendar(models.AbstractModel):
    _name = 'purchase.receiving.calendar'
    _description = 'Receiving working-time policy'

    def _is_open(self, company, now):
        calendar = company.receipt_followup_calendar_id
        if not calendar:
            return False
        aware = UTC.localize(now)
        intervals = calendar._work_intervals_batch(aware, aware + timedelta(seconds=1))[False]
        return any(start <= aware < end for start, end, records in intervals)

    def _is_overdue(self, company, expected, now):
        if not expected or expected >= now or not self._is_open(company, now):
            return False
        intervals = company.receipt_followup_calendar_id._work_intervals_batch(
            UTC.localize(expected), UTC.localize(now))[False]
        hours = sum((end - start).total_seconds() / 3600 for start, end, records in intervals)
        # A date outside working hours becomes late only after work resumes.
        return hours > company.receipt_followup_grace_hours
