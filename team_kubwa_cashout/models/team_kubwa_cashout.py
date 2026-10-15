# -*- coding: utf-8 -*-
import logging
import re
from datetime import date, datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.team_kubwa_cashout.services.eligibility_engine import TeamKubwaEligibilityEngine


_logger = logging.getLogger(__name__)


class TeamKubwaCashout(models.Model):
    _name = 'team.kubwa.cashout'
    _description = 'Team Kubwa Cash-Out'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    LOG = '[TEAM_KUBWA][CASHOUT]'
    TEAM_KUBWA_ACTION_FIELDS = {
        'team_kubwa_check_eligibility': 'sbl_require_auth_team_kubwa_check_eligibility',
        'team_kubwa_save_draft': 'sbl_require_auth_team_kubwa_save_draft',
        'team_kubwa_open_draft': 'sbl_require_auth_team_kubwa_open_draft',
        'team_kubwa_manager_override': 'sbl_require_auth_team_kubwa_manager_override',
        'team_kubwa_pay_post': 'sbl_require_auth_team_kubwa_pay_post',
    }
    _sql_constraints = [
        (
            'team_kubwa_transaction_ref_company_uniq',
            'unique(company_id, transaction_ref_normalized)',
            'Transaction reference must be unique per company.',
        ),
    ]

    name = fields.Char(default=lambda self: _('New'), readonly=True, copy=False, index=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('eligibility_checked', 'Eligibility Checked'), ('waiting_otp', 'Waiting OTP'),
        ('otp_shared', 'OTP Shared'), ('crown_confirmed', 'Crown Confirmed'), ('paid', 'Paid'),
        ('blocked', 'Blocked'), ('cancelled', 'Cancelled')
    ], default='draft', required=True, tracking=True, index=True)
    recovery_status = fields.Selection([
        ('pending_recovery', 'Pending Recovery'), ('partially_recovered', 'Partially Recovered'),
        ('recovered', 'Recovered'), ('disputed', 'Disputed'), ('cancelled', 'Cancelled')
    ], default='pending_recovery', required=True, tracking=True, index=True)
    fundi_name = fields.Char(tracking=True)
    fundi_phone = fields.Char(tracking=True, index=True)
    fundi_phone_normalized = fields.Char(compute='_compute_fundi_phone_normalized', store=True, index=True)
    fundi_partner_id = fields.Many2one('res.partner', string='Fundi Contact', tracking=True, index=True)
    requested_amount = fields.Monetary(required=True, tracking=True)
    approved_amount = fields.Monetary(tracking=True)
    paid_amount = fields.Monetary(tracking=True)
    transaction_ref = fields.Char(string='Transaction Ref', tracking=True, copy=False, index=True)
    transaction_ref_normalized = fields.Char(string='Normalized Transaction Ref', compute='_compute_transaction_ref_normalized', store=True, index=True, copy=False)
    crown_reference = fields.Char(tracking=True, copy=False)
    crown_member_name = fields.Char(string='Crown Member Name', tracking=True, copy=False)
    crown_points_redeemed = fields.Integer(string='Crown Points Redeemed', tracking=True, copy=False)
    otp_reference = fields.Char(string='OTP / OTP Reference', copy=False)
    otp_received_time = fields.Datetime(copy=False)
    otp_shared_time = fields.Datetime(copy=False)
    eligibility_policy_id = fields.Many2one('team.kubwa.eligibility.policy', tracking=True, ondelete='restrict')
    eligibility_allowed = fields.Boolean(readonly=True, copy=False)
    eligibility_requires_manager = fields.Boolean(readonly=True, copy=False)
    eligibility_reason = fields.Char(readonly=True, copy=False)
    eligibility_required_purchase = fields.Monetary(string='Required Purchases', readonly=True, copy=False)
    eligibility_actual_purchase = fields.Monetary(string='Available Purchases', readonly=True, copy=False)
    eligibility_gross_purchase = fields.Monetary(string='Gross Purchases', readonly=True, copy=False)
    eligibility_consumed_purchase = fields.Monetary(string='Previously Consumed', readonly=True, copy=False)
    eligibility_available_purchase = fields.Monetary(string='Available Purchases', readonly=True, copy=False)
    eligibility_available_after_cashout = fields.Monetary(string='Available After This Cash-Out', readonly=True, copy=False)
    eligibility_gap = fields.Monetary(string='Purchase Gap', readonly=True, copy=False)
    eligibility_period_start = fields.Datetime(string='Purchase Period Start', readonly=True, copy=False)
    eligibility_period_end = fields.Datetime(string='Purchase Period End', readonly=True, copy=False)
    eligibility_purchase_period_mode = fields.Selection(
        [('since_last_redemption', 'Since Last Redemption'), ('days', 'Last Number of Days'), ('all_time', 'All Time')],
        string='Purchase Period Mode',
        readonly=True,
        copy=False,
    )
    is_first_time = fields.Boolean(readonly=True, copy=False)
    last_cashout_id = fields.Many2one('team.kubwa.cashout', readonly=True, copy=False)
    manager_override = fields.Boolean(tracking=True, copy=False)
    override_user_id = fields.Many2one('res.users', readonly=True, copy=False)
    override_reason = fields.Selection([
        ('known_fundi', 'Known Fundi'), ('owner_approved', 'Owner Approved'),
        ('crown_activation', 'Crown Activation'), ('first_time_goodwill', 'First-Time Goodwill'),
        ('contractor_relationship', 'Contractor Relationship'), ('other', 'Other')
    ], copy=False)
    override_note = fields.Text(copy=False)
    payout_journal_id = fields.Many2one('account.journal', tracking=True)
    payout_account_id = fields.Many2one('account.account', readonly=True, copy=False)
    receivable_account_id = fields.Many2one('account.account', tracking=True)
    account_move_id = fields.Many2one('account.move', readonly=True, copy=False)
    account_move_state = fields.Selection(related='account_move_id.state', readonly=True)
    posted_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    posted_datetime = fields.Datetime(readonly=True, copy=False)
    paid_datetime = fields.Datetime(readonly=True, copy=False)
    recovered_amount = fields.Monetary(default=0.0, tracking=True)
    balance_amount = fields.Monetary(compute='_compute_balance_amount', store=True)
    pos_session_id = fields.Many2one('pos.session', readonly=True, copy=False, index=True)
    pos_config_id = fields.Many2one('pos.config', readonly=True, copy=False, index=True)
    cashier_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True, copy=False)
    authorized_supervisor_id = fields.Many2one('hr.employee', readonly=True, copy=False)
    authorization_log_id = fields.Many2one('sbl.pos.authorization.log', readonly=True, copy=False)
    authorization_action_key = fields.Char(readonly=True, copy=False)
    authorization_datetime = fields.Datetime(readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True, store=True)
    note = fields.Text()
    log_ids = fields.One2many('team.kubwa.cashout.log', 'cashout_id', readonly=True)
    ledger_ids = fields.One2many('team.kubwa.purchase.ledger', 'cashout_id', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        seen_refs = set()
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('team.kubwa.cashout') or _('New')
            transaction_ref = vals.get('transaction_ref') or vals.get('crown_reference')
            company = self.env['res.company'].browse(vals.get('company_id')).exists() if vals.get('company_id') else self.env.company
            normalized = self._normalize_transaction_ref_value(transaction_ref)
            if normalized:
                key = (company.id, normalized)
                if key in seen_refs:
                    raise ValidationError(_('Transaction reference must be unique per company.'))
                seen_refs.add(key)
                self._validate_transaction_ref_unique_values(transaction_ref, company)
        records = super().create(vals_list)
        for record in records:
            record._log_event('created', message='Cashout record created')
        return records

    def write(self, vals):
        if 'transaction_ref' in vals or 'crown_reference' in vals or 'company_id' in vals:
            for record in self:
                transaction_ref = vals.get('transaction_ref', vals.get('crown_reference', record.transaction_ref))
                company = self.env['res.company'].browse(vals['company_id']).exists() if vals.get('company_id') else record.company_id
                record._validate_transaction_ref_unique_values(transaction_ref, company, exclude=record)
        return super().write(vals)

    @api.depends('fundi_phone')
    def _compute_fundi_phone_normalized(self):
        for record in self:
            record.fundi_phone_normalized = record._normalize_phone(record.fundi_phone)

    @api.depends('transaction_ref')
    def _compute_transaction_ref_normalized(self):
        for record in self:
            transaction_ref = (record.transaction_ref or '').strip()
            record.transaction_ref_normalized = transaction_ref.casefold() if transaction_ref else False

    @api.depends('paid_amount', 'recovered_amount')
    def _compute_balance_amount(self):
        for record in self:
            record.balance_amount = max((record.paid_amount or 0.0) - (record.recovered_amount or 0.0), 0.0)

    @api.model
    def _normalize_transaction_ref_value(self, transaction_ref):
        transaction_ref = (transaction_ref or '').strip()
        return transaction_ref.casefold() if transaction_ref else False

    @api.model
    def _validate_transaction_ref_unique_values(self, transaction_ref, company, exclude=False):
        normalized = self._normalize_transaction_ref_value(transaction_ref)
        if not normalized or not company:
            return
        domain = [
            ('company_id', '=', company.id),
            ('transaction_ref_normalized', '=', normalized),
        ]
        if exclude:
            domain.append(('id', 'not in', exclude.ids))
        if self.search_count(domain):
            raise ValidationError(_('Transaction reference must be unique per company.'))

    @api.constrains('requested_amount', 'approved_amount', 'paid_amount', 'recovered_amount')
    def _check_amounts(self):
        for record in self:
            if record.requested_amount <= 0:
                raise ValidationError(_('Requested amount must be greater than zero.'))
            if record.approved_amount < 0 or record.paid_amount < 0 or record.recovered_amount < 0:
                raise ValidationError(_('Team Kubwa amounts cannot be negative.'))

    @api.constrains('transaction_ref_normalized', 'company_id')
    def _check_transaction_ref_unique(self):
        for record in self.filtered('transaction_ref_normalized'):
            duplicate = self.search_count([
                ('id', '!=', record.id),
                ('company_id', '=', record.company_id.id),
                ('transaction_ref_normalized', '=', record.transaction_ref_normalized),
            ])
            if duplicate:
                raise ValidationError(_('Transaction reference must be unique per company.'))

    @api.model
    def _normalize_phone(self, phone):
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) == 12 and digits.startswith('254'):
            return digits
        if len(digits) == 10 and digits.startswith('0'):
            return '254' + digits[1:]
        if len(digits) == 9 and digits[0] in ('7', '1'):
            return '254' + digits
        return digits

    @api.model
    def _phone_variants(self, phone):
        normalized = self._normalize_phone(phone)
        variants = [normalized] if normalized else []
        if len(normalized) == 12 and normalized.startswith('254'):
            variants += ['0' + normalized[3:], normalized[3:]]
        return list(dict.fromkeys(filter(None, variants)))

    @api.model
    def _partner_has_phone_variant(self, partner, variants):
        partner.ensure_one()
        partner_phones = [
            self._normalize_phone(partner.phone),
            self._normalize_phone(partner.mobile),
            self._normalize_phone(partner.ref),
        ]
        return bool(set(filter(None, partner_phones)).intersection(set(variants)))

    @api.model
    def _find_partner_by_phone_variants(self, variants, company_domain):
        if not variants:
            return self.env['res.partner']
        partner = self.env['res.partner'].search(
            company_domain + ['|', '|', ('phone', 'in', variants), ('mobile', 'in', variants), ('ref', 'in', variants)],
            limit=1,
        )
        if partner:
            return partner
        candidates = self.env['res.partner'].search(
            company_domain + ['|', '|', ('phone', '!=', False), ('mobile', '!=', False), ('ref', '!=', False)],
        )
        for candidate in candidates:
            if self._partner_has_phone_variant(candidate, variants):
                return candidate
        return self.env['res.partner']

    @api.model
    def _find_fundi_partner(self, phone=False, name=False):
        _logger.info('%s[FUNDI_RESOLVE][START] has_phone=%s has_name=%s user_id=%s company_id=%s', self.LOG, bool(phone), bool(name), self.env.uid, self.env.company.id)
        variants = self._phone_variants(phone)
        clean_name = (name or '').strip()
        company_domain = ['|', ('company_id', '=', False), ('company_id', '=', self.env.company.id)]
        if variants:
            partner = self._find_partner_by_phone_variants(variants, company_domain)
            if partner:
                if clean_name and clean_name.lower() not in (partner.display_name or partner.name or '').lower():
                    _logger.warning(
                        '%s[FUNDI_RESOLVE][ERROR] phone_name_mismatch partner_id=%s has_phone=True has_name=True',
                        self.LOG, partner.id,
                    )
                    raise UserError(_('The entered phone number belongs to "%s", not "%s". Select the correct customer or create/update the contact first.') % (partner.display_name, clean_name))
                _logger.info('%s[FUNDI_RESOLVE][END] partner_id=%s matched_by=phone', self.LOG, partner.id)
                return partner

        if clean_name:
            exact_partner = self.env['res.partner'].search(
                company_domain + [('name', '=ilike', clean_name)],
                limit=1,
            )
            if exact_partner:
                if variants and not self._partner_has_phone_variant(exact_partner, variants):
                    _logger.warning(
                        '%s[FUNDI_RESOLVE][ERROR] name_phone_mismatch partner_id=%s',
                        self.LOG, exact_partner.id,
                    )
                    raise UserError(_('The entered phone number is not registered for "%s". Create/update the customer contact before cash-out.') % exact_partner.display_name)
                _logger.info('%s[FUNDI_RESOLVE][END] partner_id=%s matched_by=name_exact', self.LOG, exact_partner.id)
                return exact_partner
            name_matches = self.env['res.partner'].search(
                company_domain + [('name', 'ilike', clean_name)],
                limit=2,
            )
            if len(name_matches) == 1:
                if variants and not self._partner_has_phone_variant(name_matches, variants):
                    _logger.warning(
                        '%s[FUNDI_RESOLVE][ERROR] partial_name_phone_mismatch partner_id=%s',
                        self.LOG, name_matches.id,
                    )
                    raise UserError(_('The entered phone number is not registered for "%s". Create/update the customer contact before cash-out.') % name_matches.display_name)
                _logger.info('%s[FUNDI_RESOLVE][END] partner_id=%s matched_by=name_partial', self.LOG, name_matches.id)
                return name_matches
            if len(name_matches) > 1:
                _logger.warning('%s[FUNDI_RESOLVE][ERROR] ambiguous_name=%s match_count=%s', self.LOG, clean_name, len(name_matches))
                raise UserError(_('More than one customer matches "%s". Enter the phone number or use a more specific name.') % clean_name)

        _logger.info('%s[FUNDI_RESOLVE][END] partner_id=False matched_by=none', self.LOG)
        return self.env['res.partner']

    @api.model
    def _default_policy(self, company):
        param = self.env['ir.config_parameter'].sudo().get_param('team_kubwa_cashout.default_policy_id')
        try:
            policy_id = int(param or 0)
        except (TypeError, ValueError):
            policy_id = 0
        policy = self.env['team.kubwa.eligibility.policy'].browse(policy_id).exists() if policy_id else self.env['team.kubwa.eligibility.policy']
        return policy or self.env['team.kubwa.eligibility.policy'].search([('company_id', '=', company.id), ('active', '=', True)], order='sequence, id', limit=1)

    @api.model
    def _settings(self):
        params = self.env['ir.config_parameter'].sudo()
        def as_record(model, key):
            value = params.get_param(key)
            try:
                record_id = int(value or 0)
            except (TypeError, ValueError):
                record_id = 0
            return self.env[model].browse(record_id).exists() if record_id else self.env[model]
        return {
            'enabled': str(params.get_param('team_kubwa_cashout.enabled', 'False')).lower() in ('1', 'true', 'yes', 'on'),
            'dealer_line': params.get_param('team_kubwa_cashout.dealer_line', ''),
            'require_transaction_ref': str(
                params.get_param(
                    'team_kubwa_cashout.require_transaction_ref',
                    params.get_param('team_kubwa_cashout.require_crown_reference', 'False'),
                )
            ).lower() not in ('0', 'false', 'no', 'off'),
            'receivable_account': as_record('account.account', 'team_kubwa_cashout.receivable_account_id'),
            'default_payout_journal': as_record('account.journal', 'team_kubwa_cashout.default_payout_journal_id'),
        }

    @api.model
    def _transaction_ref_from_payload(self, payload):
        return ((payload or {}).get('transaction_ref') or (payload or {}).get('crown_reference') or '').strip()

    @api.model
    def _validate_transaction_ref_for_journal(self, settings, payout_journal, payload):
        transaction_ref = self._transaction_ref_from_payload(payload)
        _logger.info(
            '%s[TRANSACTION_REF_VALIDATE][START] journal_id=%s journal_type=%s required_setting=%s has_transaction_ref=%s user_id=%s',
            self.LOG,
            payout_journal.id,
            payout_journal.type,
            settings['require_transaction_ref'],
            bool(transaction_ref),
            self.env.uid,
        )
        if settings['require_transaction_ref'] and payout_journal.type == 'bank' and not transaction_ref:
            _logger.warning(
                '%s[TRANSACTION_REF_VALIDATE][ERROR] journal_id=%s journal_type=%s reason=missing_transaction_ref user_id=%s',
                self.LOG,
                payout_journal.id,
                payout_journal.type,
                self.env.uid,
            )
            raise UserError(_('Transaction reference is required for bank payout journals.'))
        _logger.info('%s[TRANSACTION_REF_VALIDATE][END] required=%s', self.LOG, settings['require_transaction_ref'] and payout_journal.type == 'bank')
        return transaction_ref

    @api.model
    def pos_get_config(self, pos_session_id=False):
        settings = self._settings()
        journals = self.env['account.journal'].search([('type', 'in', ('cash', 'bank', 'general')), ('company_id', '=', self.env.company.id)], order='type, name')
        return {
            'enabled': settings['enabled'],
            'dealer_line': settings['dealer_line'],
            'require_transaction_ref': settings['require_transaction_ref'],
            'receivable_configured': bool(settings['receivable_account']),
            'default_payout_journal_id': settings['default_payout_journal'].id,
            'journals': [{'id': journal.id, 'name': journal.display_name, 'type': journal.type} for journal in journals],
        }

    @api.model
    def _team_kubwa_cashier_employee(self, payload):
        payload = payload or {}
        employee = self.env['hr.employee']
        cashier_id = int(payload.get('cashier_id') or 0)
        if cashier_id:
            employee = self.env['hr.employee'].sudo().browse(cashier_id).exists()
        if not employee and self.env.user.employee_id:
            employee = self.env.user.employee_id.sudo()
        return employee

    @api.model
    def _team_kubwa_authorization_from_payload(self, payload, action_key):
        authorizations = (payload or {}).get('authorizations') or {}
        authorization = authorizations.get(action_key) or {}
        if not authorization and (payload or {}).get('authorization', {}).get('action_key') == action_key:
            authorization = (payload or {}).get('authorization') or {}
        return authorization

    @api.model
    def _validate_team_kubwa_pos_authorization(self, payload, action_key, allow_autosave=False):
        payload = payload or {}
        _logger.info(
            '%s[AUTH][START] action_key=%s autosave=%s user_id=%s',
            self.LOG,
            action_key,
            bool(payload.get('autosave')),
            self.env.uid,
        )
        if allow_autosave and payload.get('autosave'):
            _logger.info('%s[AUTH][END] action_key=%s allowed=True reason=autosave', self.LOG, action_key)
            return self.env['sbl.pos.authorization.log']

        field_name = self.TEAM_KUBWA_ACTION_FIELDS.get(action_key)
        if not field_name:
            _logger.info('%s[AUTH][END] action_key=%s allowed=True reason=unmapped_action', self.LOG, action_key)
            return self.env['sbl.pos.authorization.log']

        cashier = self._team_kubwa_cashier_employee(payload)
        if not cashier:
            _logger.warning('%s[AUTH][ERROR] action_key=%s reason=missing_cashier user_id=%s', self.LOG, action_key, self.env.uid)
            raise UserError(_('Cashier employee is required for Team Kubwa authorization.'))

        if not cashier[field_name]:
            _logger.info(
                '%s[AUTH][END] action_key=%s cashier_id=%s allowed=True reason=employee_unrestricted',
                self.LOG,
                action_key,
                cashier.id,
            )
            return self.env['sbl.pos.authorization.log']

        authorization = self._team_kubwa_authorization_from_payload(payload, action_key)
        auth_log_id = int(authorization.get('authorization_log_id') or 0)
        supervisor_id = int(authorization.get('supervisor_id') or 0)
        auth_log = self.env['sbl.pos.authorization.log'].sudo().browse(auth_log_id).exists()
        pos_session_id = int(payload.get('pos_session_id') or 0)
        cutoff = fields.Datetime.to_datetime(fields.Datetime.now()) - timedelta(minutes=10)
        create_date = fields.Datetime.to_datetime(auth_log.create_date) if auth_log else False
        valid = bool(
            auth_log
            and auth_log.status == 'approved'
            and auth_log.action_key == action_key
            and auth_log.cashier_id.id == cashier.id
            and auth_log.supervisor_id.id == supervisor_id
            and (not pos_session_id or auth_log.pos_session_id.id == pos_session_id)
            and create_date
            and create_date >= cutoff
        )
        if not valid:
            _logger.warning(
                '%s[AUTH][ERROR] action_key=%s cashier_id=%s auth_log_id=%s supervisor_id=%s reason=invalid_or_expired',
                self.LOG,
                action_key,
                cashier.id,
                auth_log_id,
                supervisor_id,
            )
            raise UserError(_('Supervisor authorization is required for this Team Kubwa action.'))

        _logger.info(
            '%s[AUTH][END] action_key=%s cashier_id=%s supervisor_id=%s auth_log_id=%s allowed=True',
            self.LOG,
            action_key,
            cashier.id,
            supervisor_id,
            auth_log.id,
        )
        return auth_log

    @api.model
    def _team_kubwa_authorization_values(self, auth_log, action_key):
        if not auth_log:
            return {}
        return {
            'authorized_supervisor_id': auth_log.supervisor_id.id,
            'authorization_log_id': auth_log.id,
            'authorization_action_key': action_key,
            'authorization_datetime': fields.Datetime.now(),
        }

    @api.model
    def pos_check_eligibility(self, payload):
        _logger.info('%s[ELIGIBILITY][START] payload_keys=%s user_id=%s', self.LOG, sorted((payload or {}).keys()), self.env.uid)
        payload = payload or {}
        self._validate_team_kubwa_pos_authorization(payload, 'team_kubwa_check_eligibility')
        policy = self._default_policy(self.env.company)
        if not policy:
            return {'allowed': False, 'reason': 'missing_policy', 'message': _('No Team Kubwa eligibility policy is configured.')}
        phone = payload.get('phone') or ''
        fundi_name = payload.get('fundi_name') or ''
        if not phone and not fundi_name:
            raise UserError(_('Enter a fundi name or phone number.'))
        amount = float(payload.get('requested_amount') or 0.0)
        partner = self._find_fundi_partner(phone, fundi_name)
        if not partner:
            result = {
                'allowed': False,
                'requires_manager': False,
                'requires_customer_creation': bool(phone and fundi_name),
                'reason': 'customer_not_found',
                'is_first_time': True,
                'required_purchase': 0.0,
                'actual_purchase': 0.0,
                'gross_purchase': 0.0,
                'consumed_purchase': 0.0,
                'available_purchase': 0.0,
                'available_after_cashout': 0.0,
                'period_start': False,
                'period_end': fields.Datetime.now(),
                'purchase_period_mode': policy.purchase_period_mode,
                'gap': 0.0,
                'last_cashout_id': False,
                'last_cashout_date': False,
                'policy_id': policy.id,
                'policy_name': policy.display_name,
                'partner_id': False,
                'partner_name': False,
                'message': _('No customer found. Create the customer before checking first-time fundi eligibility.') if phone and fundi_name else _('Enter both fundi name and phone number to create a new customer.'),
            }
            _logger.info('%s[ELIGIBILITY][END] policy_id=%s result=%s', self.LOG, policy.id, result)
            return result
        self._validate_no_fully_unpaid_cod_orders(partner, company=self.env.company)
        self._validate_no_open_unpaid_invoices(partner, company=self.env.company)
        result = TeamKubwaEligibilityEngine(self.env).evaluate(policy, phone, amount, partner=partner)
        result.update({
            'policy_id': policy.id,
            'policy_name': policy.display_name,
            'partner_id': partner.id,
            'partner_name': partner.display_name if partner else False,
            'requires_customer_creation': False,
            'message': self._eligibility_message(result),
        })
        _logger.info('%s[ELIGIBILITY][END] policy_id=%s result=%s', self.LOG, policy.id, result)
        return result

    @api.model
    def _eligibility_message(self, result):
        return {
            'first_time_allowed': _('First-time fundi is within the configured limit.'),
            'first_time_limit_exceeded': _('First-time fundi limit exceeded.'),
            'eligible_by_purchase': _('Fundi meets the configured purchase requirement.'),
            'manager_required': _('Eligible, but manager approval is required for this amount.'),
            'insufficient_purchase': _('Fundi purchase history is below the configured requirement.'),
        }.get(result.get('reason'), _('Eligibility checked.'))

    @api.model
    def _pos_draft_state(self, payload):
        step = (payload or {}).get('step') or 'fundi'
        if step == 'confirm':
            return 'crown_confirmed'
        if (payload or {}).get('otp_received'):
            return 'otp_shared'
        if step == 'otp':
            return 'waiting_otp'
        if (payload or {}).get('eligibility'):
            return 'eligibility_checked'
        return 'draft'

    @api.model
    def _pos_draft_values(self, payload, partner, policy, session):
        payload = payload or {}
        eligibility = payload.get('eligibility') or {}
        auth_log = self._validate_team_kubwa_pos_authorization(
            payload,
            'team_kubwa_save_draft',
            allow_autosave=True,
        )
        otp_received = bool(payload.get('otp_received'))
        try:
            points_redeemed = int(payload.get('crown_points_redeemed') or 0)
        except (TypeError, ValueError):
            points_redeemed = 0
        transaction_ref = self._transaction_ref_from_payload(payload)
        values = {
            'fundi_name': payload.get('fundi_name') or partner.display_name,
            'fundi_phone': payload.get('phone') or partner.phone or partner.mobile,
            'fundi_partner_id': partner.id,
            'requested_amount': float(payload.get('requested_amount') or 0.0),
            'approved_amount': float(payload.get('approved_amount') or payload.get('requested_amount') or 0.0),
            'paid_amount': 0.0,
            'transaction_ref': transaction_ref or False,
            'crown_reference': transaction_ref or False,
            'crown_member_name': (payload.get('crown_member_name') or '').strip(),
            'crown_points_redeemed': points_redeemed,
            'otp_reference': (payload.get('otp_reference') or '').strip() or False,
            'otp_received_time': fields.Datetime.now() if otp_received else False,
            'otp_shared_time': fields.Datetime.now() if otp_received else False,
            'eligibility_policy_id': int(eligibility.get('policy_id') or policy.id or 0) or False,
            'eligibility_allowed': bool(eligibility.get('allowed')),
            'eligibility_requires_manager': bool(eligibility.get('requires_manager')),
            'eligibility_reason': eligibility.get('reason') or False,
            'eligibility_required_purchase': float(eligibility.get('required_purchase') or 0.0),
            'eligibility_actual_purchase': float(eligibility.get('actual_purchase') or 0.0),
            'eligibility_gross_purchase': float(eligibility.get('gross_purchase') or 0.0),
            'eligibility_consumed_purchase': float(eligibility.get('consumed_purchase') or 0.0),
            'eligibility_available_purchase': float(eligibility.get('available_purchase') or eligibility.get('actual_purchase') or 0.0),
            'eligibility_available_after_cashout': float(eligibility.get('available_after_cashout') or 0.0),
            'eligibility_gap': float(eligibility.get('gap') or 0.0),
            'eligibility_period_start': eligibility.get('period_start') or False,
            'eligibility_period_end': eligibility.get('period_end') or False,
            'eligibility_purchase_period_mode': eligibility.get('purchase_period_mode') or policy.purchase_period_mode,
            'is_first_time': bool(eligibility.get('is_first_time')),
            'last_cashout_id': eligibility.get('last_cashout_id') or False,
            'manager_override': bool(payload.get('manager_override')),
            'override_user_id': self.env.user.id if payload.get('manager_override') else False,
            'override_reason': payload.get('override_reason') or False,
            'override_note': payload.get('override_note') or False,
            'payout_journal_id': int(payload.get('payout_journal_id') or 0) or False,
            'pos_session_id': session.id if session else False,
            'pos_config_id': session.config_id.id if session else False,
            'company_id': self.env.company.id,
            'state': self._pos_draft_state(payload),
            'note': payload.get('note') or False,
        }
        values.update(self._team_kubwa_authorization_values(auth_log, 'team_kubwa_save_draft'))
        return values

    @api.model
    def _has_eligibility_snapshot(self, vals):
        return bool(
            vals.get('eligibility_reason')
            or vals.get('eligibility_required_purchase')
            or vals.get('eligibility_gross_purchase')
            or vals.get('eligibility_consumed_purchase')
            or vals.get('eligibility_available_purchase')
        )

    @api.model
    def pos_save_draft_cashout(self, payload):
        _logger.info('%s[DRAFT_SAVE][START] payload_keys=%s user_id=%s', self.LOG, sorted((payload or {}).keys()), self.env.uid)
        payload = payload or {}
        requested_amount = float(payload.get('requested_amount') or 0.0)
        if requested_amount <= 0:
            raise UserError(_('Requested amount must be greater than zero before saving a draft.'))
        partner = self.env['res.partner'].browse(int(payload.get('partner_id') or 0)).exists()
        if not partner:
            partner = self._find_fundi_partner(payload.get('phone') or '', payload.get('fundi_name') or '')
        if not partner:
            raise UserError(_('Identify or create the fundi customer before saving a draft.'))
        policy = self._default_policy(self.env.company)
        session = self.env['pos.session'].browse(int(payload.get('pos_session_id') or 0)).exists()
        vals = self._pos_draft_values(payload, partner, policy, session)
        draft = self.browse(int(payload.get('draft_id') or 0)).exists()
        if draft:
            if draft.company_id != self.env.company:
                raise UserError(_('You cannot update a Team Kubwa draft from another company.'))
            if draft.state in ('paid', 'cancelled'):
                raise UserError(_('This Team Kubwa cash-out can no longer be edited as a draft.'))
            old_state = draft.state
            draft.write(vals)
            draft._log_event('draft_updated', old_state=old_state, new_state=draft.state, message='POS draft updated', payload={'step': payload.get('step')})
            if vals.get('authorization_log_id'):
                draft._log_event(
                    'authorization',
                    message='Supervisor authorization linked to draft update',
                    payload={
                        'authorization_log_id': vals.get('authorization_log_id'),
                        'authorization_action_key': vals.get('authorization_action_key'),
                        'authorized_supervisor_id': vals.get('authorized_supervisor_id'),
                    },
                )
            if self._has_eligibility_snapshot(vals) and old_state != draft.state:
                draft._create_purchase_ledger_entry('eligibility_check', 'Draft eligibility snapshot')
            _logger.info('%s[DRAFT_SAVE][END] draft_id=%s action=updated state=%s', self.LOG, draft.id, draft.state)
            return draft._pos_payload()
        draft = self.create(vals)
        draft._log_event('draft_saved', message='POS draft saved', payload={'step': payload.get('step')})
        if vals.get('authorization_log_id'):
            draft._log_event(
                'authorization',
                message='Supervisor authorization linked to draft save',
                payload={
                    'authorization_log_id': vals.get('authorization_log_id'),
                    'authorization_action_key': vals.get('authorization_action_key'),
                    'authorized_supervisor_id': vals.get('authorized_supervisor_id'),
                },
            )
        if self._has_eligibility_snapshot(vals):
            draft._create_purchase_ledger_entry('eligibility_check', 'Draft eligibility snapshot')
        _logger.info('%s[DRAFT_SAVE][END] draft_id=%s action=created state=%s', self.LOG, draft.id, draft.state)
        return draft._pos_payload()

    @api.model
    def pos_resume_draft_cashout(self, draft_id, payload=None):
        _logger.info('%s[DRAFT_RESUME][START] draft_id=%s user_id=%s', self.LOG, draft_id, self.env.uid)
        payload = payload or {}
        self._validate_team_kubwa_pos_authorization(payload, 'team_kubwa_open_draft')
        draft = self.browse(int(draft_id or 0)).exists()
        if not draft or draft.company_id != self.env.company:
            raise UserError(_('Team Kubwa draft was not found.'))
        if draft.state in ('paid', 'cancelled'):
            raise UserError(_('This Team Kubwa cash-out is no longer an open draft.'))
        draft._log_event('draft_resumed', message='POS draft resumed')
        _logger.info('%s[DRAFT_RESUME][END] draft_id=%s state=%s', self.LOG, draft.id, draft.state)
        return draft._pos_payload()

    @api.model
    def _validate_manager_override(self, policy, eligibility, override_reason):
        _logger.info(
            '%s[OVERRIDE_VALIDATE][START] policy_id=%s reason=%s override_reason=%s user_id=%s',
            self.LOG, policy.id if policy else False, (eligibility or {}).get('reason'), override_reason, self.env.uid,
        )
        eligibility = eligibility or {}
        if eligibility.get('reason') == 'first_time_limit_exceeded' and override_reason == 'first_time_goodwill':
            _logger.warning(
                '%s[OVERRIDE_VALIDATE][ERROR] first_time_goodwill_limit_exceeded policy_id=%s first_time_limit=%s requested_reason=%s',
                self.LOG, policy.id if policy else False, policy.first_time_limit_amount if policy else False, override_reason,
            )
            raise UserError(_('First-time goodwill cannot exceed the configured first-time limit. Use another approved manager override reason or reduce the amount.'))
        if override_reason == 'first_time_goodwill' and not eligibility.get('is_first_time'):
            _logger.warning(
                '%s[OVERRIDE_VALIDATE][ERROR] repeated_first_time_goodwill policy_id=%s last_cashout_id=%s',
                self.LOG, policy.id if policy else False, eligibility.get('last_cashout_id'),
            )
            raise UserError(_('First-time goodwill can only be used before the fundi has any paid Team Kubwa cash-out.'))
        _logger.info('%s[OVERRIDE_VALIDATE][END] policy_id=%s allowed=True', self.LOG, policy.id if policy else False)

    @api.model
    def _validate_cashout_amounts_against_eligibility(self, requested_amount, approved_amount, paid_amount):
        _logger.info(
            '%s[AMOUNT_VALIDATE][START] requested=%s approved=%s paid=%s user_id=%s',
            self.LOG, requested_amount, approved_amount, paid_amount, self.env.uid,
        )
        if approved_amount > requested_amount:
            _logger.warning(
                '%s[AMOUNT_VALIDATE][ERROR] approved_gt_requested requested=%s approved=%s paid=%s',
                self.LOG, requested_amount, approved_amount, paid_amount,
            )
            raise UserError(_('Approved amount cannot exceed the amount checked for eligibility. Go back and check eligibility again for the higher amount.'))
        if paid_amount > approved_amount:
            _logger.warning(
                '%s[AMOUNT_VALIDATE][ERROR] paid_gt_approved requested=%s approved=%s paid=%s',
                self.LOG, requested_amount, approved_amount, paid_amount,
            )
            raise UserError(_('Paid amount cannot exceed the approved amount.'))
        _logger.info('%s[AMOUNT_VALIDATE][END] requested=%s approved=%s paid=%s', self.LOG, requested_amount, approved_amount, paid_amount)

    @api.model
    def _validate_first_time_limit(self, policy, eligibility, paid_amount, override_reason=False):
        eligibility = eligibility or {}
        _logger.info(
            '%s[FIRST_TIME_LIMIT][START] policy_id=%s is_first_time=%s amount=%s limit=%s override_reason=%s user_id=%s',
            self.LOG,
            policy.id if policy else False,
            eligibility.get('is_first_time'),
            paid_amount,
            policy.first_time_limit_amount if policy else False,
            override_reason,
            self.env.uid,
        )
        if not policy or not policy.first_time_allowed or not eligibility.get('is_first_time'):
            _logger.info('%s[FIRST_TIME_LIMIT][END] applicable=False', self.LOG)
            return
        if eligibility.get('reason') == 'eligible_by_purchase':
            _logger.info('%s[FIRST_TIME_LIMIT][END] applicable=False reason=eligible_by_purchase', self.LOG)
            return
        limit = policy.first_time_limit_amount or 0.0
        if paid_amount > limit:
            if override_reason and override_reason != 'first_time_goodwill':
                _logger.info(
                    '%s[FIRST_TIME_LIMIT][END] allowed_by_override=True policy_id=%s amount=%s limit=%s override_reason=%s',
                    self.LOG, policy.id, paid_amount, limit, override_reason,
                )
                return
            _logger.warning(
                '%s[FIRST_TIME_LIMIT][ERROR] amount_gt_limit policy_id=%s amount=%s limit=%s override_reason=%s',
                self.LOG, policy.id, paid_amount, limit, override_reason,
            )
            if override_reason == 'first_time_goodwill':
                raise UserError(_('First-time goodwill cannot exceed the configured first-time limit. Use another approved manager override reason or reduce the amount.'))
            raise UserError(_('First-time cash-out cannot exceed the configured first-time limit. Reduce the amount and check eligibility again.'))
        _logger.info('%s[FIRST_TIME_LIMIT][END] applicable=True allowed=True', self.LOG)

    @api.model
    def _get_fully_unpaid_cod_orders(self, partner, company=False):
        _logger.info(
            '%s[COD_BLOCK][START] partner_id=%s company_id=%s user_id=%s',
            self.LOG, partner.id if partner else False, company.id if company else False, self.env.uid,
        )
        if not partner:
            _logger.info('%s[COD_BLOCK][END] partner_id=False count=0 total_open=0.0', self.LOG)
            return self.env['pos.order']

        company = company or self.env.company
        commercial_partner = partner.commercial_partner_id
        domain = [
            ('is_cod', '=', True),
            ('partner_id', 'child_of', commercial_partner.id),
            ('cod_state', 'in', ('pending', 'out_for_delivery', 'delivered', 'partial')),
            ('amount_total', '>', 0),
        ]
        if company:
            domain.append(('company_id', '=', company.id))

        candidates = self.env['pos.order'].search(domain, order='date_order asc, id asc')
        blocking_orders = candidates.filtered(
            lambda order: (
                round(order._cod_paid_total(), 2) <= 0.0
                and round(order._cod_return_total(), 2) <= 0.0
                and round(order._cod_open_amount(), 2) > 0.0
            )
        )
        total_open = sum(order._cod_open_amount() for order in blocking_orders)
        _logger.info(
            '%s[COD_BLOCK][END] partner_id=%s candidate_count=%s blocking_count=%s total_open=%s',
            self.LOG, commercial_partner.id, len(candidates), len(blocking_orders), round(total_open, 2),
        )
        return blocking_orders

    @api.model
    def _validate_no_fully_unpaid_cod_orders(self, partner, company=False):
        blocking_orders = self._get_fully_unpaid_cod_orders(partner, company=company)
        if not blocking_orders:
            return
        total_open = sum(order._cod_open_amount() for order in blocking_orders)
        refs = ', '.join(blocking_orders[:3].mapped(lambda order: order.name or order.pos_reference or str(order.id)))
        if len(blocking_orders) > 3:
            refs = _('%s, and %s more') % (refs, len(blocking_orders) - 3)
        _logger.warning(
            '%s[COD_BLOCK][ERROR] partner_id=%s blocking_count=%s total_open=%s refs=%s',
            self.LOG, partner.commercial_partner_id.id if partner else False, len(blocking_orders), round(total_open, 2), refs,
        )
        raise UserError(_(
            'Cash-out blocked. This customer has %(count)s fully unpaid COD order(s) totaling %(amount).2f. '
            'Collect or return the COD order(s) before Team Kubwa cash-out. Orders: %(refs)s'
        ) % {
            'count': len(blocking_orders),
            'amount': total_open,
            'refs': refs,
        })

    @api.model
    def _get_open_unpaid_invoices(self, partner, company=False):
        _logger.info(
            '%s[INVOICE_BLOCK][START] partner_id=%s company_id=%s user_id=%s',
            self.LOG, partner.id if partner else False, company.id if company else False, self.env.uid,
        )
        if not partner:
            _logger.info('%s[INVOICE_BLOCK][END] partner_id=False count=0 total_residual=0.0', self.LOG)
            return self.env['account.move']

        company = company or self.env.company
        commercial_partner = partner.commercial_partner_id
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('partner_id', 'child_of', commercial_partner.id),
            ('amount_residual', '>', 0),
        ]
        if company:
            domain.append(('company_id', '=', company.id))

        invoices = self.env['account.move'].search(domain, order='invoice_date_due asc, invoice_date asc, id asc')
        total_residual = sum(invoices.mapped('amount_residual'))
        _logger.info(
            '%s[INVOICE_BLOCK][END] partner_id=%s blocking_count=%s total_residual=%s',
            self.LOG, commercial_partner.id, len(invoices), round(total_residual, 2),
        )
        return invoices

    @api.model
    def _validate_no_open_unpaid_invoices(self, partner, company=False):
        invoices = self._get_open_unpaid_invoices(partner, company=company)
        if not invoices:
            return
        total_residual = sum(invoices.mapped('amount_residual'))
        refs = ', '.join(invoices[:3].mapped(lambda move: move.name or move.ref or str(move.id)))
        if len(invoices) > 3:
            refs = _('%s, and %s more') % (refs, len(invoices) - 3)
        _logger.warning(
            '%s[INVOICE_BLOCK][ERROR] partner_id=%s blocking_count=%s total_residual=%s refs=%s',
            self.LOG, partner.commercial_partner_id.id if partner else False, len(invoices), round(total_residual, 2), refs,
        )
        raise UserError(_(
            'Cash-out blocked. This customer has %(count)s open unpaid invoice(s) totaling %(amount).2f. '
            'Collect or reconcile the invoice(s) before Team Kubwa cash-out. Invoices: %(refs)s'
        ) % {
            'count': len(invoices),
            'amount': total_residual,
            'refs': refs,
        })

    @api.model
    def _validate_otp_confirmation(self, payload):
        payload = payload or {}
        try:
            points_redeemed = int(payload.get('crown_points_redeemed') or 0)
        except (TypeError, ValueError):
            points_redeemed = 0
        _logger.info(
            '%s[OTP_VALIDATE][START] has_otp_reference=%s has_member_name=%s points=%s otp_received=%s user_id=%s',
            self.LOG,
            bool((payload.get('otp_reference') or '').strip()),
            bool((payload.get('crown_member_name') or '').strip()),
            points_redeemed,
            bool(payload.get('otp_received')),
            self.env.uid,
        )
        if not (payload.get('otp_reference') or '').strip():
            _logger.warning('%s[OTP_VALIDATE][ERROR] missing_otp_reference user_id=%s', self.LOG, self.env.uid)
            raise UserError(_('OTP / OTP reference is required before posting a Team Kubwa cash-out.'))
        if not (payload.get('crown_member_name') or '').strip():
            _logger.warning('%s[OTP_VALIDATE][ERROR] missing_crown_member_name user_id=%s', self.LOG, self.env.uid)
            raise UserError(_('Crown member name from the OTP SMS is required before posting a Team Kubwa cash-out.'))
        if points_redeemed <= 0:
            _logger.warning('%s[OTP_VALIDATE][ERROR] missing_crown_points_redeemed user_id=%s', self.LOG, self.env.uid)
            raise UserError(_('Crown points redeemed from the OTP SMS must be greater than zero.'))
        if not payload.get('otp_received'):
            _logger.warning('%s[OTP_VALIDATE][ERROR] otp_not_marked_received user_id=%s', self.LOG, self.env.uid)
            raise UserError(_('Mark OTP received/shared before posting a Team Kubwa cash-out.'))
        _logger.info('%s[OTP_VALIDATE][END] allowed=True user_id=%s', self.LOG, self.env.uid)

    @api.model
    def pos_create_paid_cashout(self, payload):
        _logger.info('%s[PAY][START] payload_keys=%s user_id=%s', self.LOG, sorted((payload or {}).keys()), self.env.uid)
        payload = payload or {}
        pay_auth_log = self._validate_team_kubwa_pos_authorization(payload, 'team_kubwa_pay_post')
        settings = self._settings()
        if not settings['enabled']:
            raise UserError(_('Team Kubwa Cash-Out is disabled in settings.'))
        if not settings['receivable_account']:
            raise UserError(_('Configure the Team Kubwa receivable account before paying fundis.'))
        requested_amount = float(payload.get('requested_amount') or 0.0)
        approved_amount = float(payload.get('approved_amount') or requested_amount)
        paid_amount = float(payload.get('paid_amount') or approved_amount)
        if paid_amount <= 0:
            raise UserError(_('Paid amount must be greater than zero.'))
        self._validate_cashout_amounts_against_eligibility(requested_amount, approved_amount, paid_amount)
        self._validate_otp_confirmation(payload)
        policy = self._default_policy(self.env.company)
        if not policy:
            raise UserError(_('No Team Kubwa eligibility policy is configured.'))
        phone = payload.get('phone') or ''
        if not phone and not payload.get('fundi_name'):
            raise UserError(_('Enter a fundi name or phone number.'))
        partner = self._find_fundi_partner(phone, payload.get('fundi_name'))
        if not partner:
            raise UserError(_('Create/select the fundi customer before posting this cash-out.'))
        self._validate_no_fully_unpaid_cod_orders(partner, company=self.env.company)
        self._validate_no_open_unpaid_invoices(partner, company=self.env.company)
        eligibility_amount = paid_amount
        eligibility = TeamKubwaEligibilityEngine(self.env).evaluate(policy, phone, eligibility_amount, partner=partner)
        override = bool(payload.get('manager_override'))
        override_reason = payload.get('override_reason') if override else False
        if override and not override_reason:
            raise UserError(_('Select a manager override reason.'))
        override_auth_log = self.env['sbl.pos.authorization.log']
        if override:
            override_auth_log = self._validate_team_kubwa_pos_authorization(payload, 'team_kubwa_manager_override')
        self._validate_first_time_limit(policy, eligibility, paid_amount, override_reason=override_reason)
        if (not eligibility['allowed'] or eligibility['requires_manager']) and not override:
            raise UserError(_('This cash-out is not eligible without manager override.'))
        if override:
            self._validate_manager_override(policy, eligibility, override_reason)
        payout_journal = self.env['account.journal'].browse(int(payload.get('payout_journal_id') or 0)).exists() or settings['default_payout_journal']
        if not payout_journal:
            raise UserError(_('Select a payout journal.'))
        transaction_ref = self._validate_transaction_ref_for_journal(settings, payout_journal, payload)
        payout_account = payout_journal.default_account_id
        if not payout_account:
            raise UserError(_('The selected payout journal has no default account.'))
        session = self.env['pos.session'].browse(int(payload.get('pos_session_id') or 0)).exists()
        cashout_values = {
            'fundi_name': payload.get('fundi_name') or (partner.display_name if partner else False),
            'fundi_phone': phone,
            'fundi_partner_id': partner.id,
            'requested_amount': requested_amount,
            'approved_amount': approved_amount,
            'paid_amount': paid_amount,
            'transaction_ref': transaction_ref or False,
            'crown_reference': transaction_ref or False,
            'crown_member_name': (payload.get('crown_member_name') or '').strip(),
            'crown_points_redeemed': int(payload.get('crown_points_redeemed') or 0),
            'otp_reference': payload.get('otp_reference') or False,
            'otp_received_time': fields.Datetime.now() if payload.get('otp_received') else False,
            'otp_shared_time': fields.Datetime.now(),
            'eligibility_policy_id': policy.id,
            'eligibility_allowed': eligibility['allowed'],
            'eligibility_requires_manager': eligibility['requires_manager'],
            'eligibility_reason': eligibility['reason'],
            'eligibility_required_purchase': eligibility['required_purchase'],
            'eligibility_actual_purchase': eligibility['actual_purchase'],
            'eligibility_gross_purchase': eligibility.get('gross_purchase', eligibility['actual_purchase']),
            'eligibility_consumed_purchase': eligibility.get('consumed_purchase', 0.0),
            'eligibility_available_purchase': eligibility.get('available_purchase', eligibility['actual_purchase']),
            'eligibility_available_after_cashout': eligibility.get('available_after_cashout', eligibility['actual_purchase'] - eligibility['required_purchase']),
            'eligibility_gap': eligibility['gap'],
            'eligibility_period_start': eligibility.get('period_start') or False,
            'eligibility_period_end': eligibility.get('period_end') or False,
            'eligibility_purchase_period_mode': eligibility.get('purchase_period_mode') or policy.purchase_period_mode,
            'is_first_time': eligibility['is_first_time'],
            'last_cashout_id': eligibility['last_cashout_id'],
            'manager_override': override,
            'override_user_id': self.env.user.id if override else False,
            'override_reason': payload.get('override_reason') or False,
            'override_note': payload.get('override_note') or False,
            'payout_journal_id': payout_journal.id,
            'payout_account_id': payout_account.id,
            'receivable_account_id': settings['receivable_account'].id,
            'pos_session_id': session.id,
            'pos_config_id': session.config_id.id if session else False,
            'company_id': self.env.company.id,
            'state': 'crown_confirmed',
            'note': payload.get('note') or False,
        }
        audit_auth_log = pay_auth_log or override_auth_log
        audit_action_key = 'team_kubwa_pay_post' if pay_auth_log else 'team_kubwa_manager_override'
        cashout_values.update(self._team_kubwa_authorization_values(audit_auth_log, audit_action_key))
        cashout = self.browse(int(payload.get('draft_id') or 0)).exists()
        if cashout:
            if cashout.company_id != self.env.company:
                raise UserError(_('You cannot pay a Team Kubwa draft from another company.'))
            if cashout.state in ('paid', 'cancelled'):
                raise UserError(_('This Team Kubwa draft can no longer be paid.'))
            old_state = cashout.state
            cashout.write(cashout_values)
            cashout._log_event('draft_updated', old_state=old_state, new_state='crown_confirmed', message='Draft updated before payment')
        else:
            cashout = self.create(cashout_values)
        if cashout_values.get('authorization_log_id'):
            cashout._log_event(
                'authorization',
                message='Supervisor authorization linked to payment',
                payload={
                    'authorization_log_id': cashout_values.get('authorization_log_id'),
                    'authorization_action_key': cashout_values.get('authorization_action_key'),
                    'authorized_supervisor_id': cashout_values.get('authorized_supervisor_id'),
                },
            )
        cashout._log_event('eligibility_checked', message=cashout._eligibility_message(eligibility), payload=eligibility)
        cashout._create_purchase_ledger_entry('eligibility_check', 'Payment eligibility snapshot')
        if override:
            cashout._log_event('manager_override', message='Manager override accepted')
        cashout._log_event('otp_shared', message='OTP marked as shared')
        cashout._post_cashout_move()
        now = fields.Datetime.now()
        cashout.write({'state': 'paid', 'paid_datetime': now, 'posted_by_id': self.env.user.id, 'posted_datetime': now})
        cashout._create_purchase_ledger_entry('cashout_consumption', 'Cash-out consumed purchase value')
        cashout._log_event('paid', old_state='crown_confirmed', new_state='paid', message='Cashout paid and receivable posted')
        _logger.info('%s[PAY][END] cashout_id=%s move_id=%s', self.LOG, cashout.id, cashout.account_move_id.id)
        return cashout._pos_payload()

    def _post_cashout_move(self):
        for cashout in self:
            if cashout.account_move_id:
                continue
            _logger.info('%s[POST_MOVE][START] cashout_id=%s amount=%s', self.LOG, cashout.id, cashout.paid_amount)
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': cashout.payout_journal_id.id,
                'date': fields.Date.context_today(cashout),
                'ref': cashout.name,
                'line_ids': [
                    (0, 0, {'name': _('Team Kubwa receivable - %s') % (cashout.fundi_phone or cashout.name), 'account_id': cashout.receivable_account_id.id, 'partner_id': cashout.fundi_partner_id.id, 'debit': cashout.paid_amount, 'credit': 0.0}),
                    (0, 0, {'name': _('Team Kubwa payout - %s') % (cashout.fundi_phone or cashout.name), 'account_id': cashout.payout_account_id.id, 'partner_id': cashout.fundi_partner_id.id, 'debit': 0.0, 'credit': cashout.paid_amount}),
                ],
            })
            move.action_post()
            cashout.account_move_id = move.id
            cashout._log_event('account_move_posted', message='Receivable journal entry posted', payload={'move_id': move.id})
            _logger.info('%s[POST_MOVE][END] cashout_id=%s move_id=%s', self.LOG, cashout.id, move.id)

    @api.model
    def pos_list_cashouts(self, limit=30):
        records = self.search([('company_id', '=', self.env.company.id)], order='create_date desc, id desc', limit=limit or 30)
        return [record._pos_payload() for record in records]

    def _create_purchase_ledger_entry(self, entry_type, message=False):
        for cashout in self:
            if not cashout.fundi_partner_id or not cashout.eligibility_policy_id:
                continue
            _logger.info(
                '%s[PURCHASE_LEDGER][START] cashout_id=%s entry_type=%s gross=%s consumed=%s available=%s required=%s',
                self.LOG,
                cashout.id,
                entry_type,
                cashout.eligibility_gross_purchase,
                cashout.eligibility_consumed_purchase,
                cashout.eligibility_available_purchase,
                cashout.eligibility_required_purchase,
            )
            if entry_type == 'cashout_consumption':
                consumed_by_entry = cashout.eligibility_required_purchase
                running_available = cashout.eligibility_available_after_cashout
            else:
                consumed_by_entry = 0.0
                running_available = cashout.eligibility_available_purchase
            ledger = self.env['team.kubwa.purchase.ledger'].create({
                'entry_type': entry_type,
                'cashout_id': cashout.id,
                'partner_id': cashout.fundi_partner_id.id,
                'policy_id': cashout.eligibility_policy_id.id,
                'company_id': cashout.company_id.id,
                'currency_id': cashout.currency_id.id,
                'pos_session_id': cashout.pos_session_id.id,
                'user_id': self.env.user.id,
                'entry_datetime': fields.Datetime.now(),
                'purchase_period_mode': cashout.eligibility_purchase_period_mode,
                'period_start': cashout.eligibility_period_start,
                'period_end': cashout.eligibility_period_end,
                'gross_purchase': cashout.eligibility_gross_purchase,
                'previously_consumed_purchase': cashout.eligibility_consumed_purchase,
                'available_purchase': cashout.eligibility_available_purchase,
                'required_purchase': cashout.eligibility_required_purchase,
                'cashout_amount': cashout.paid_amount or cashout.approved_amount or cashout.requested_amount,
                'consumed_purchase': consumed_by_entry,
                'running_available_purchase': running_available,
                'manager_override': cashout.manager_override,
                'override_reason': cashout.override_reason or False,
                'note': message or '',
            })
            cashout._log_event(
                'purchase_ledger',
                message=message or 'Purchase consumption ledger updated',
                payload={
                    'ledger_id': ledger.id,
                    'entry_type': entry_type,
                    'gross_purchase': cashout.eligibility_gross_purchase,
                    'previously_consumed_purchase': cashout.eligibility_consumed_purchase,
                    'available_purchase': cashout.eligibility_available_purchase,
                    'required_purchase': cashout.eligibility_required_purchase,
                    'consumed_purchase': consumed_by_entry,
                    'running_available_purchase': running_available,
                },
            )
            _logger.info(
                '%s[PURCHASE_LEDGER][END] cashout_id=%s ledger_id=%s entry_type=%s running_available=%s',
                self.LOG, cashout.id, ledger.id, entry_type, running_available,
            )

    def _pos_payload(self):
        self.ensure_one()
        eligibility = {
            'allowed': self.eligibility_allowed,
            'requires_manager': self.eligibility_requires_manager,
            'reason': self.eligibility_reason,
            'is_first_time': self.is_first_time,
            'required_purchase': self.eligibility_required_purchase,
            'actual_purchase': self.eligibility_actual_purchase,
            'gross_purchase': self.eligibility_gross_purchase,
            'consumed_purchase': self.eligibility_consumed_purchase,
            'available_purchase': self.eligibility_available_purchase,
            'available_after_cashout': self.eligibility_available_after_cashout,
            'period_start': self.eligibility_period_start,
            'period_end': self.eligibility_period_end,
            'purchase_period_mode': self.eligibility_purchase_period_mode,
            'gap': self.eligibility_gap,
            'last_cashout_id': self.last_cashout_id.id,
            'last_cashout_date': self.last_cashout_id.paid_datetime if self.last_cashout_id else False,
            'policy_id': self.eligibility_policy_id.id,
            'policy_name': self.eligibility_policy_id.display_name,
            'partner_id': self.fundi_partner_id.id,
            'partner_name': self.fundi_partner_id.display_name,
            'message': self._eligibility_message({'reason': self.eligibility_reason}),
        } if self.eligibility_policy_id or self.eligibility_reason else False
        return {
            'id': self.id, 'name': self.name, 'state': self.state, 'recovery_status': self.recovery_status,
            'fundi_name': self.fundi_name or '', 'fundi_phone': self.fundi_phone or '',
            'fundi_partner_id': self.fundi_partner_id.id, 'fundi_partner_name': self.fundi_partner_id.display_name or '',
            'requested_amount': self.requested_amount, 'approved_amount': self.approved_amount,
            'paid_amount': self.paid_amount, 'transaction_ref': self.transaction_ref or self.crown_reference or '',
            'crown_reference': self.transaction_ref or self.crown_reference or '',
            'crown_member_name': self.crown_member_name or '', 'crown_points_redeemed': self.crown_points_redeemed,
            'otp_reference': self.otp_reference or '', 'otp_received': bool(self.otp_received_time),
            'eligibility': eligibility,
            'manager_override': self.manager_override,
            'override_reason': self.override_reason or '', 'override_note': self.override_note or '',
            'payout_journal_id': self.payout_journal_id.id,
            'cashier': self.cashier_id.display_name, 'paid_datetime': self.paid_datetime,
            'authorized_supervisor': self.authorized_supervisor_id.display_name or '',
            'authorization_log_id': self.authorization_log_id.id,
            'authorization_action_key': self.authorization_action_key or '',
            'write_date': self.write_date,
            'journal_entry': self.account_move_id.name or '', 'balance_amount': self.balance_amount,
        }

    def action_cancel_cashout(self):
        for cashout in self:
            if cashout.state == 'paid':
                raise UserError(_('Paid cash-outs cannot be cancelled in phase 1. Reverse the journal entry manually if needed.'))
            old_state = cashout.state
            cashout.write({'state': 'cancelled', 'recovery_status': 'cancelled'})
            cashout._log_event('cancelled', old_state=old_state, new_state='cancelled', message='Cashout cancelled')

    def _log_event(self, event_type, old_state=False, new_state=False, message=False, payload=False):
        for cashout in self:
            self.env['team.kubwa.cashout.log'].create({
                'cashout_id': cashout.id, 'event_type': event_type, 'old_state': old_state or False,
                'new_state': new_state or cashout.state, 'user_id': self.env.user.id,
                'pos_session_id': cashout.pos_session_id.id, 'message': message or '',
                'safe_payload_json': self._json_safe_payload(payload or {}),
            })

    @api.model
    def _json_safe_payload(self, value):
        if isinstance(value, dict):
            return {key: self._json_safe_payload(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe_payload(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, models.BaseModel):
            return value.ids
        return value


class TeamKubwaCashoutLog(models.Model):
    _name = 'team.kubwa.cashout.log'
    _description = 'Team Kubwa Cash-Out Log'
    _order = 'create_date desc, id desc'

    cashout_id = fields.Many2one('team.kubwa.cashout', required=True, ondelete='cascade', index=True)
    event_type = fields.Selection([
        ('created', 'Created'), ('eligibility_checked', 'Eligibility Checked'), ('otp_received', 'OTP Received'),
        ('otp_shared', 'OTP Shared'), ('crown_confirmed', 'Crown Confirmed'), ('manager_override', 'Manager Override'),
        ('draft_saved', 'Draft Saved'), ('draft_updated', 'Draft Updated'), ('draft_resumed', 'Draft Resumed'),
        ('authorization', 'Supervisor Authorization'), ('purchase_ledger', 'Purchase Ledger'),
        ('account_move_posted', 'Journal Entry Posted'), ('paid', 'Paid'), ('blocked', 'Blocked'),
        ('cancelled', 'Cancelled'), ('recovery_status_changed', 'Recovery Status Changed')
    ], required=True, index=True)
    old_state = fields.Char()
    new_state = fields.Char()
    user_id = fields.Many2one('res.users', readonly=True)
    pos_session_id = fields.Many2one('pos.session', readonly=True)
    message = fields.Char()
    safe_payload_json = fields.Json()


class TeamKubwaPurchaseLedger(models.Model):
    _name = 'team.kubwa.purchase.ledger'
    _description = 'Team Kubwa Purchase Consumption Ledger'
    _order = 'entry_datetime desc, id desc'
    LOG = '[TEAM_KUBWA][PURCHASE_LEDGER]'

    entry_datetime = fields.Datetime(default=fields.Datetime.now, required=True, index=True, readonly=True)
    entry_type = fields.Selection([
        ('eligibility_check', 'Eligibility Check'),
        ('cashout_consumption', 'Cash-Out Consumption'),
        ('reversal', 'Reversal'),
    ], required=True, index=True, readonly=True)
    cashout_id = fields.Many2one('team.kubwa.cashout', required=True, ondelete='cascade', index=True, readonly=True)
    partner_id = fields.Many2one('res.partner', required=True, index=True, readonly=True)
    policy_id = fields.Many2one('team.kubwa.eligibility.policy', readonly=True)
    company_id = fields.Many2one('res.company', required=True, index=True, readonly=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    pos_session_id = fields.Many2one('pos.session', readonly=True)
    user_id = fields.Many2one('res.users', readonly=True)
    purchase_period_mode = fields.Selection([
        ('since_last_redemption', 'Since Last Redemption'),
        ('days', 'Last Number of Days'),
        ('all_time', 'All Time'),
    ], readonly=True)
    period_start = fields.Datetime(readonly=True)
    period_end = fields.Datetime(readonly=True)
    gross_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    previously_consumed_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    available_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    required_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    cashout_amount = fields.Monetary(currency_field='currency_id', readonly=True)
    consumed_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    running_available_purchase = fields.Monetary(currency_field='currency_id', readonly=True)
    manager_override = fields.Boolean(readonly=True)
    override_reason = fields.Selection([
        ('known_fundi', 'Known Fundi'), ('owner_approved', 'Owner Approved'),
        ('crown_activation', 'Crown Activation'), ('first_time_goodwill', 'First-Time Goodwill'),
        ('contractor_relationship', 'Contractor Relationship'), ('other', 'Other')
    ], readonly=True)
    note = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info('%s[CREATE][START] count=%s user_id=%s', self.LOG, len(vals_list), self.env.uid)
        records = super().create(vals_list)
        _logger.info('%s[CREATE][END] ids=%s', self.LOG, records.ids)
        return records

