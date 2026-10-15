# -*- coding: utf-8 -*-
import logging

from odoo import fields, models
from odoo.tools import str2bool


_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    LOG = '[TEAM_KUBWA][SETTINGS]'

    team_kubwa_enabled = fields.Boolean(string='Enable Team Kubwa Cash-Out', config_parameter='team_kubwa_cashout.enabled')
    team_kubwa_dealer_line = fields.Char(string='Dealer Registered Line', config_parameter='team_kubwa_cashout.dealer_line')
    team_kubwa_default_policy_id = fields.Many2one('team.kubwa.eligibility.policy', string='Default Team Kubwa Policy', config_parameter='team_kubwa_cashout.default_policy_id')
    team_kubwa_receivable_account_id = fields.Many2one('account.account', string='Team Kubwa Receivable Account', config_parameter='team_kubwa_cashout.receivable_account_id')
    team_kubwa_default_payout_journal_id = fields.Many2one('account.journal', string='Default Team Kubwa Payout Journal', config_parameter='team_kubwa_cashout.default_payout_journal_id', domain="[('type', 'in', ('cash', 'bank', 'general'))]")
    team_kubwa_require_transaction_ref = fields.Boolean(string='Require Transaction Reference for Bank Payouts', default=False)

    def get_values(self):
        _logger.info('%s[GET_VALUES][START] user_id=%s company_id=%s', self.LOG, self.env.uid, self.env.company.id)
        res = super().get_values()
        params = self.env['ir.config_parameter'].sudo()
        raw_value = params.get_param('team_kubwa_cashout.require_transaction_ref')
        if raw_value in (None, False):
            raw_value = params.get_param('team_kubwa_cashout.require_crown_reference', 'False')
        res['team_kubwa_require_transaction_ref'] = str2bool(raw_value, default=False)
        _logger.info('%s[GET_VALUES][END] require_transaction_ref=%s raw=%s', self.LOG, res['team_kubwa_require_transaction_ref'], raw_value)
        return res

    def set_values(self):
        _logger.info('%s[SET_VALUES][START] user_id=%s company_id=%s require_transaction_ref=%s', self.LOG, self.env.uid, self.env.company.id, self.team_kubwa_require_transaction_ref)
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'team_kubwa_cashout.require_transaction_ref',
            'True' if self.team_kubwa_require_transaction_ref else 'False',
        )
        _logger.info('%s[SET_VALUES][END] require_transaction_ref=%s', self.LOG, self.team_kubwa_require_transaction_ref)

