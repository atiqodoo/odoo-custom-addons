import logging
from datetime import datetime, time, timedelta

from pytz import UTC, timezone, NonExistentTimeError, AmbiguousTimeError

from odoo import _, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PurchaseDeliveryPlanning(models.AbstractModel):
    _name = 'purchase.delivery.planning'
    _description = 'Calendar-aware vendor delivery planning'

    def _validate_calendar(self, calendar, company):
        if not calendar or not calendar.active or not calendar.attendance_ids or calendar.flexible_hours:
            raise ValidationError(_('Choose an active receiving calendar with fixed working hours.'))
        calendar.check_access('read')
        if calendar.company_id and calendar.company_id != company:
            raise ValidationError(_('The receiving calendar must be shared or belong to the purchasing company.'))

    def _validate_preferred_time(self, calendar, preferred):
        if not 0 <= preferred < 24 or not any(
            attendance.hour_from <= preferred <= attendance.hour_to
            for attendance in calendar.attendance_ids if not attendance.resource_id and attendance.day_period != 'lunch'
        ):
            raise ValidationError(_('Preferred arrival time must fall within at least one receiving working interval.'))

    def _is_valid_arrival(self, calendar, arrival):
        aware = UTC.localize(arrival)
        intervals = calendar._work_intervals_batch(aware - timedelta(seconds=1), aware + timedelta(seconds=1))[False]
        # Closing time itself is a valid promised deadline.
        return any(start <= aware <= end for start, end, records in intervals)

    def _calculate(self, company, calendar, start, days, hours, day_hours, preferred=False, preferred_time=0):
        _logger.debug('[OVERDUE_RECEIPT][DELIVERY_CALCULATE][START] company_id=%s calendar_id=%s start=%s days=%s hours=%s',
                      company.id, calendar.id, start, days, hours)
        try:
            self._validate_calendar(calendar, company)
            if not start or days < 0 or hours < 0 or day_hours <= 0:
                raise ValidationError(_('Choose a start time, nonnegative days/hours and positive hours per day.'))
            if preferred:
                self._validate_preferred_time(calendar, preferred_time)
            result = calendar.plan_hours(days * day_hours + hours, UTC.localize(start), compute_leaves=True)
            if not result:
                raise ValidationError(_('No receiving working interval is available for this delivery duration.'))
            horizon = UTC.localize(start + timedelta(days=company.delivery_planning_horizon_days))
            if result > horizon:
                raise ValidationError(_('Delivery exceeds the company delivery planning lookahead.'))
            if preferred:
                tz = timezone(calendar.tz)
                day = result.astimezone(tz).date()
                while True:
                    if day > horizon.astimezone(tz).date():
                        raise ValidationError(_('No preferred receiving time is available within the company delivery planning lookahead.'))
                    local = datetime.combine(day, time.min) + timedelta(seconds=round(preferred_time * 3600))
                    try:
                        candidate = tz.localize(local, is_dst=None).astimezone(UTC)
                    except (NonExistentTimeError, AmbiguousTimeError):
                        candidate = None
                    if candidate and result <= candidate <= horizon and self._is_valid_arrival(calendar, candidate.replace(tzinfo=None)):
                        result = candidate
                        break
                    next_day = tz.localize(datetime.combine(day + timedelta(days=1), time.min)).astimezone(UTC)
                    opening = calendar.plan_hours(0, next_day, compute_leaves=True)
                    if not opening:
                        raise ValidationError(_('No receiving interval is available at the preferred arrival time.'))
                    day = opening.astimezone(tz).date()
            arrival = result.astimezone(UTC).replace(tzinfo=None)
            _logger.debug('[OVERDUE_RECEIPT][DELIVERY_CALCULATE][END] company_id=%s arrival=%s working_hours=%s',
                          company.id, arrival, days * day_hours + hours)
            return arrival
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][DELIVERY_CALCULATE][ERROR] company_id=%s calendar_id=%s', company.id, calendar.id)
            raise

    def _policy_values(self, partner, company):
        policy = self.env['purchase.vendor.delivery.policy'].search([
            ('partner_id', '=', partner.commercial_partner_id.id), ('company_id', '=', company.id), ('active', '=', True),
        ], limit=1)
        return {
            'delivery_policy_id': policy.id,
            'delivery_days': policy.days if policy else 0,
            'delivery_hours': policy.hours if policy else 0,
            'delivery_day_hours': company.delivery_hours_per_day,
            'delivery_calendar_id': (policy.calendar_id or company.receipt_followup_calendar_id).id,
            'delivery_use_preferred_time': policy.use_preferred_time if policy else False,
            'delivery_preferred_time': policy.preferred_time if policy else 0,
        }
