import logging

from odoo import models
from odoo.tools import float_is_zero
from odoo.tools.image import image_data_uri

from ..utils.image_validation import tint_png_payload

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _lpo_report_config_enabled(self, key):
        return self.env['ir.config_parameter'].sudo().get_param(
            f'purchase_net_price_compute.{key}',
            'False',
        ) == 'True'

    def _lpo_report_show_cost(self):
        return self._lpo_report_config_enabled('lpo_report_show_cost')

    def _lpo_report_show_discount(self):
        return self._lpo_report_config_enabled('lpo_report_show_discount')

    def _lpo_report_show_tax(self):
        return self._lpo_report_config_enabled('lpo_report_show_tax')

    def _lpo_report_show_subtotal(self):
        return self._lpo_report_config_enabled('lpo_report_show_subtotal')

    def _lpo_report_show_total(self):
        return self._lpo_report_config_enabled('lpo_report_show_total')

    def _lpo_report_show_promotion(self):
        return self._lpo_report_config_enabled('lpo_report_show_promotion')

    def _lpo_report_show_grade_volume(self):
        return self._lpo_report_config_enabled('lpo_report_show_grade_volume')

    def _lpo_report_format_float(self, value, precision_digits=2):
        """Format report quantities without useless .00 decimals."""
        try:
            value = float(value or 0.0)
        except (TypeError, ValueError):
            return value

        rounded_value = round(value, precision_digits)
        if float_is_zero(rounded_value - round(rounded_value), precision_digits=precision_digits):
            return str(int(round(rounded_value)))

        return f"{rounded_value:.{precision_digits}f}".rstrip('0').rstrip('.')

    def _lpo_report_lines(self):
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: not (
                'is_promotion_foc' in line._fields
                and line.is_promotion_foc
            )
        )

    def _lpo_report_signature_user(self):
        self.ensure_one()
        user = self.user_id.sudo()
        has_signature = bool(user.lpo_signature_png)
        _logger.debug(
            "LPO report signature lookup order_id=%s order=%s user_id=%s login=%s has_signature=%s",
            self.id,
            self.name,
            user.id if user else False,
            user.login if user else False,
            has_signature,
        )
        if not has_signature:
            _logger.info(
                "LPO report rendered without signature image order_id=%s order=%s user_id=%s",
                self.id,
                self.name,
                user.id if user else False,
            )
            return False
        return user

    def _lpo_report_preparer_needs_approval(self):
        self.ensure_one()
        user = self.user_id.sudo()
        is_authorized = bool(user) and (
            user._has_group('purchase.group_purchase_manager')
            or user._has_group('base.group_system')
            or user._has_group('base.group_erp_manager')
        )
        needs_approval = not is_authorized
        _logger.debug(
            "LPO approval signature decision order_id=%s order=%s user_id=%s login=%s needs_approval=%s",
            self.id,
            self.name,
            user.id if user else False,
            user.login if user else False,
            needs_approval,
        )
        return needs_approval

    def _lpo_report_stamp_company(self):
        self.ensure_one()
        company = self.company_id.sudo()
        has_stamp = bool(company.lpo_rubber_stamp_png)
        _logger.debug(
            "LPO rubber stamp lookup order_id=%s order=%s company_id=%s has_stamp=%s",
            self.id,
            self.name,
            company.id,
            has_stamp,
        )
        if not has_stamp:
            _logger.info(
                "LPO report rendered without rubber stamp image order_id=%s order=%s company_id=%s",
                self.id,
                self.name,
                company.id,
            )
            return False
        return company

    def _lpo_report_blue_image_uri(self, image_payload, label='LPO image'):
        tinted_payload = tint_png_payload(
            image_payload,
            rgb=(20, 55, 145),
            label=label,
        )
        return image_data_uri(tinted_payload) if tinted_payload else False
