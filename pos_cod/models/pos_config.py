# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cod_enabled = fields.Boolean(
        string='Enable COD',
        default=False,
        help='Allow cashiers to dispatch orders as Cash on Delivery from this POS.',
    )
    cod_ar_account_id = fields.Many2one(
        'account.account',
        string='COD Receivable Account',
        domain=[('account_type', '=', 'asset_receivable'), ('reconcile', '=', True)],
        help=(
            'Dedicated AR account for COD dispatches (e.g. 1150 - COD Receivables). '
            'Must be account_type=asset_receivable and reconcile=True so that '
            'Odoo\'s reconciliation engine can match the confirmation entry against '
            'the payment entry when cash is collected. '
            'This account is excluded from pos_credit_limit credit-limit checks.'
        ),
    )

    @api.constrains('cod_enabled', 'cod_ar_account_id')
    def _check_cod_account_required(self):
        for config in self:
            if config.cod_enabled and not config.cod_ar_account_id:
                raise ValidationError(
                    'POS Configuration "%s": a COD Receivable Account is required '
                    'when COD is enabled. Please set it under POS Settings → COD.' % config.name
                )

    @api.constrains('cod_ar_account_id')
    def _check_cod_account_type(self):
        for config in self:
            acct = config.cod_ar_account_id
            if not acct:
                continue
            if acct.account_type != 'asset_receivable':
                raise ValidationError(
                    'COD Receivable Account "%s" must have account_type = asset_receivable. '
                    'Current type: %s.' % (acct.name, acct.account_type)
                )
            if not acct.reconcile:
                raise ValidationError(
                    'COD Receivable Account "%s" must have "Allow Reconciliation" enabled. '
                    'Without it the confirmation entry cannot be matched against the '
                    'payment entry when cash is collected.' % acct.name
                )
