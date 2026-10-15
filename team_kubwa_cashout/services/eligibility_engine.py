# -*- coding: utf-8 -*-
import logging
import re
from datetime import timedelta

from odoo import fields


_logger = logging.getLogger(__name__)


class TeamKubwaEligibilityEngine:
    LOG = '[TEAM_KUBWA][ELIGIBILITY]'

    def __init__(self, env):
        self.env = env

    def evaluate(self, policy, phone, requested_amount, partner=False):
        _logger.info('%s[START] policy_id=%s partner_id=%s amount=%s company_id=%s user_id=%s', self.LOG, policy.id, partner.id if partner else False, requested_amount, policy.company_id.id, self.env.uid)
        last_cashout = self._last_paid_cashout(phone, partner, policy.company_id)
        is_first_time = not bool(last_cashout)
        period_start = self._period_start(policy, last_cashout)
        period_end = fields.Datetime.now()
        gross_purchase = self._purchase_amount(policy, partner, period_start)
        consumed_purchase = self._consumed_purchase_amount(policy, phone, partner, period_start)
        actual_purchase = gross_purchase - consumed_purchase
        required_purchase = policy.get_required_purchase(requested_amount)
        manager_required = policy.requires_manager_approval(requested_amount)
        purchase_allowed = actual_purchase >= required_purchase
        if purchase_allowed:
            allowed = True
            reason = 'eligible_by_purchase'
        elif is_first_time and policy.first_time_allowed:
            allowed = requested_amount <= (policy.first_time_limit_amount or 0.0)
            reason = 'first_time_allowed' if allowed else 'first_time_limit_exceeded'
            required_purchase = 0.0 if allowed else required_purchase
        else:
            allowed = False
            reason = 'insufficient_purchase'
        if allowed and manager_required:
            reason = 'manager_required'
        result = {
            'allowed': bool(allowed),
            'requires_manager': bool(manager_required),
            'reason': reason,
            'is_first_time': is_first_time,
            'required_purchase': required_purchase,
            'actual_purchase': actual_purchase,
            'gross_purchase': gross_purchase,
            'consumed_purchase': consumed_purchase,
            'available_purchase': actual_purchase,
            'available_after_cashout': actual_purchase - required_purchase,
            'period_start': period_start,
            'period_end': period_end,
            'purchase_period_mode': policy.purchase_period_mode,
            'gap': max(required_purchase - actual_purchase, 0.0),
            'last_cashout_id': last_cashout.id if last_cashout else False,
            'last_cashout_date': last_cashout.paid_datetime if last_cashout else False,
        }
        _logger.info('%s[END] policy_id=%s partner_id=%s result=%s', self.LOG, policy.id, partner.id if partner else False, result)
        return result

    def _last_paid_cashout(self, phone, partner, company):
        clauses = []
        if partner:
            clauses.append(('fundi_partner_id', '=', partner.id))
        normalized = self._normalize_phone(phone)
        if normalized:
            clauses.append(('fundi_phone_normalized', '=', normalized))
        if not clauses:
            return self.env['team.kubwa.cashout']
        domain = [('company_id', '=', company.id), ('state', '=', 'paid')]
        domain += [clauses[0]] if len(clauses) == 1 else ['|'] + clauses[:2]
        return self.env['team.kubwa.cashout'].search(domain, order='paid_datetime desc, id desc', limit=1)

    def _period_start(self, policy, last_cashout):
        if policy.purchase_period_mode == 'since_last_redemption' and last_cashout and last_cashout.paid_datetime:
            return last_cashout.paid_datetime
        if policy.purchase_period_mode == 'days' and policy.purchase_period_days:
            return fields.Datetime.now() - timedelta(days=policy.purchase_period_days)
        return False

    def _purchase_amount(self, policy, partner, period_start=False):
        if not partner:
            return 0.0
        domain = [('partner_id', '=', partner.id), ('company_id', '=', policy.company_id.id), ('state', 'not in', ('cancel', 'draft'))]
        if period_start:
            domain.append(('date_order', '>', period_start))
        groups = self.env['pos.order'].read_group(domain, ['amount_total:sum'], [])
        return groups[0].get('amount_total', 0.0) if groups else 0.0

    def _consumed_purchase_amount(self, policy, phone, partner=False, period_start=False):
        _logger.info(
            '%s[CONSUMPTION][START] policy_id=%s partner_id=%s period_start=%s user_id=%s',
            self.LOG, policy.id, partner.id if partner else False, period_start, self.env.uid,
        )
        domain = [('company_id', '=', policy.company_id.id), ('state', '=', 'paid')]
        if period_start:
            domain.append(('paid_datetime', '>', period_start))
        clauses = []
        if partner:
            clauses.append(('fundi_partner_id', '=', partner.id))
        normalized = self._normalize_phone(phone)
        if normalized:
            clauses.append(('fundi_phone_normalized', '=', normalized))
        if not clauses:
            _logger.info('%s[CONSUMPTION][END] consumed=0.0 reason=no_partner_or_phone', self.LOG)
            return 0.0
        domain += [clauses[0]] if len(clauses) == 1 else ['|'] + clauses[:2]
        cashouts = self.env['team.kubwa.cashout'].search(domain)
        consumed = sum(self._cashout_consumed_purchase(policy, cashout) for cashout in cashouts)
        _logger.info(
            '%s[CONSUMPTION][END] policy_id=%s count=%s consumed=%s',
            self.LOG, policy.id, len(cashouts), consumed,
        )
        return consumed

    def _cashout_consumed_purchase(self, policy, cashout):
        if cashout.eligibility_required_purchase:
            return cashout.eligibility_required_purchase
        amount = cashout.paid_amount or cashout.approved_amount or cashout.requested_amount
        return policy.get_required_purchase(amount)

    @staticmethod
    def _normalize_phone(phone):
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) == 12 and digits.startswith('254'):
            return digits
        if len(digits) == 10 and digits.startswith('0'):
            return '254' + digits[1:]
        if len(digits) == 9 and digits[0] in ('7', '1'):
            return '254' + digits
        return digits

