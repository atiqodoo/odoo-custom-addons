# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TeamKubwaEligibilityPolicy(models.Model):
    _name = 'team.kubwa.eligibility.policy'
    _description = 'Team Kubwa Eligibility Policy'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    first_time_allowed = fields.Boolean(string='Allow First-Time Cash-Out', default=True, tracking=True)
    first_time_limit_amount = fields.Monetary(string='First-Time Limit', currency_field='currency_id', tracking=True)
    purchase_ratio = fields.Float(string='Purchase Ratio', default=10.0, tracking=True)
    minimum_purchase_amount = fields.Monetary(string='Minimum Purchase Amount', currency_field='currency_id', tracking=True)
    high_value_approval_amount = fields.Monetary(string='Manager Approval Above', currency_field='currency_id', tracking=True)
    purchase_period_mode = fields.Selection(
        [('since_last_redemption', 'Since Last Redemption'), ('days', 'Last Number of Days'), ('all_time', 'All Time')],
        default='since_last_redemption',
        required=True,
        tracking=True,
    )
    purchase_period_days = fields.Integer(default=90, tracking=True)
    tier_ids = fields.One2many('team.kubwa.eligibility.policy.tier', 'policy_id', string='Tier Rules', copy=True)

    @api.constrains('first_time_limit_amount', 'purchase_ratio', 'minimum_purchase_amount', 'high_value_approval_amount', 'purchase_period_days')
    def _check_non_negative_values(self):
        for policy in self:
            if policy.first_time_limit_amount < 0 or policy.purchase_ratio < 0 or policy.minimum_purchase_amount < 0 or policy.high_value_approval_amount < 0 or policy.purchase_period_days < 0:
                raise ValidationError(_('Team Kubwa policy numeric values cannot be negative.'))

    def _matching_tier(self, amount):
        self.ensure_one()
        amount = amount or 0.0
        return self.tier_ids.filtered(
            lambda tier: tier.active and amount >= (tier.amount_from or 0.0) and (not tier.amount_to or amount <= tier.amount_to)
        ).sorted(lambda tier: (tier.amount_from, tier.id))[:1]

    def get_required_purchase(self, amount):
        self.ensure_one()
        tier = self._matching_tier(amount)
        if tier:
            return tier.get_required_purchase(amount)
        return max((amount or 0.0) * (self.purchase_ratio or 0.0), self.minimum_purchase_amount or 0.0)

    def requires_manager_approval(self, amount):
        self.ensure_one()
        tier = self._matching_tier(amount)
        return bool((tier and tier.requires_manager_approval) or (self.high_value_approval_amount and amount > self.high_value_approval_amount))


class TeamKubwaEligibilityPolicyTier(models.Model):
    _name = 'team.kubwa.eligibility.policy.tier'
    _description = 'Team Kubwa Eligibility Policy Tier'
    _order = 'policy_id, amount_from, amount_to, id'

    policy_id = fields.Many2one('team.kubwa.eligibility.policy', required=True, ondelete='cascade')
    active = fields.Boolean(default=True)
    currency_id = fields.Many2one('res.currency', related='policy_id.currency_id', readonly=True)
    amount_from = fields.Monetary(currency_field='currency_id', required=True)
    amount_to = fields.Monetary(currency_field='currency_id', help='Leave zero for no upper limit.')
    required_purchase_amount = fields.Monetary(currency_field='currency_id')
    purchase_ratio = fields.Float()
    requires_manager_approval = fields.Boolean()

    @api.constrains('amount_from', 'amount_to', 'required_purchase_amount', 'purchase_ratio')
    def _check_tier_values(self):
        for tier in self:
            if tier.amount_from < 0 or tier.amount_to < 0 or tier.required_purchase_amount < 0 or tier.purchase_ratio < 0:
                raise ValidationError(_('Team Kubwa tier numeric values cannot be negative.'))
            if tier.amount_to and tier.amount_to < tier.amount_from:
                raise ValidationError(_('Tier maximum cannot be lower than tier minimum.'))

    def get_required_purchase(self, amount):
        self.ensure_one()
        if self.required_purchase_amount:
            return self.required_purchase_amount
        ratio = self.purchase_ratio or self.policy_id.purchase_ratio or 0.0
        return max((amount or 0.0) * ratio, self.policy_id.minimum_purchase_amount or 0.0)

