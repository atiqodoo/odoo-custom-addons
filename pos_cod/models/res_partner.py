# -*- coding: utf-8 -*-
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

_COD = '[COD][ResPartner]'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def get_credit_info(self, partner_id, company_id=False):
        """Override to subtract open COD AR from total_due.

        pos_credit_limit uses partner.credit (which includes ALL asset_receivable
        accounts) as total_due. COD dispatches post to a separate COD AR account
        that is intentionally excluded from credit-limit enforcement.

        Strategy: call super() to get the base result, then query the open balance
        on the COD AR account specifically and subtract it from total_due.
        deposit_balance is recalculated from the corrected total_due.

        If no COD AR account is configured for the company, the result is returned
        unmodified — COD AR will naturally flow into credit-limit checks until the
        account is configured.
        """
        result = super().get_credit_info(partner_id, company_id=company_id)

        if result.get('error'):
            return result

        cod_ar_account = self._cod_get_ar_account_for_company(company_id)
        if not cod_ar_account:
            _logger.warning(
                '%s get_credit_info: no COD AR account configured for company_id=%s — '
                'returning unmodified result (COD AR counts toward credit limit).',
                _COD, company_id,
            )
            return result

        partner = self.browse(partner_id)
        commercial = partner.commercial_partner_id

        open_cod_ar = self._cod_get_open_ar_balance(commercial, cod_ar_account, company_id)

        if open_cod_ar == 0.0:
            _logger.debug(
                '%s get_credit_info: partner=%s — open_cod_ar=0, no adjustment.',
                _COD, commercial.name,
            )
            return result

        original_total_due = result['total_due']
        corrected_total_due = round(original_total_due - open_cod_ar, 2)
        corrected_deposit = max(0.0, -corrected_total_due)

        _logger.warning(
            '%s get_credit_info\n'
            '  partner         : %s (id=%s)\n'
            '  original_total_due : %.2f\n'
            '  open_cod_ar        : %.2f  (excluded from credit limit)\n'
            '  corrected_total_due: %.2f\n'
            '  corrected_deposit  : %.2f',
            _COD,
            commercial.name, partner_id,
            original_total_due,
            open_cod_ar,
            corrected_total_due,
            corrected_deposit,
        )

        result['total_due'] = corrected_total_due
        result['deposit_balance'] = corrected_deposit
        return result

    def _cod_get_open_ar_balance(self, commercial_partner, cod_ar_account, company_id=False):
        """Sum amount_residual on open COD AR lines for this partner.

        Uses amount_residual (not debit) so partial payments are correctly
        reflected — a partly-paid COD order contributes only its remaining balance.

        Filters:
          - account_id = the dedicated COD AR account
          - move_id.is_cod_entry = True (confirmation entries only, not payments)
          - move_id.state = posted
          - amount_residual > 0 (not fully reconciled)
          - partner child_of commercial_partner (matches Odoo's partner.credit logic)
        """
        try:
            domain = [
                ('partner_id', 'child_of', commercial_partner.id),
                ('account_id', '=', cod_ar_account.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.is_cod_entry', '=', True),
                ('amount_residual', '>', 0),
            ]
            if company_id:
                domain.append(('company_id', '=', company_id))

            lines = self.env['account.move.line'].search(domain)
            total = sum(lines.mapped('amount_residual'))
            result = round(float(total), 2)

            _logger.debug(
                '%s _cod_get_open_ar_balance: partner=%s account=%s lines=%s total=%.2f',
                _COD, commercial_partner.name, cod_ar_account.name, len(lines), result,
            )
            return result

        except Exception as exc:
            _logger.error(
                '%s _cod_get_open_ar_balance: FAILED for partner %s: %s — returning 0.',
                _COD, commercial_partner.name, exc, exc_info=True,
            )
            return 0.0

    def _cod_get_ar_account_for_company(self, company_id=False):
        """Return the COD AR account configured in pos.config for this company.

        Returns None if not configured — callers must handle the None case
        (fail-open: COD AR flows into credit checks until account is configured).
        """
        try:
            domain = [('cod_ar_account_id', '!=', False)]
            if company_id:
                domain.append(('company_id', '=', company_id))
            config = self.env['pos.config'].sudo().search(domain, limit=1)
            return config.cod_ar_account_id if config else None
        except Exception as exc:
            _logger.error('%s _cod_get_ar_account_for_company: %s', _COD, exc)
            return None
