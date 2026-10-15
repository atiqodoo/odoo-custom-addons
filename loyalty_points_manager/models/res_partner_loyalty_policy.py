# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_PARTNER_HEAD = "[LPM_PARTNER_LOYALTY_POLICY]"


class ResPartnerLoyaltyPolicy(models.Model):
    _inherit = "res.partner"

    lpm_can_earn_loyalty_points = fields.Boolean(
        string="Can Earn Loyalty Points",
        default=True,
        help=(
            "When disabled, this customer cannot earn loyalty points from POS, "
            "COD payment collection, or backend Sales Orders."
        ),
    )
    lpm_can_redeem_loyalty_points = fields.Boolean(
        string="Can Redeem Loyalty Points",
        default=True,
        help="When disabled, this customer cannot spend/redeem loyalty points.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        for field_name in self._lpm_loyalty_policy_pos_fields():
            if field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list

    @api.model
    def _lpm_loyalty_policy_pos_fields(self):
        return [
            "lpm_can_earn_loyalty_points",
            "lpm_can_redeem_loyalty_points",
            "commercial_partner_id",
        ]

    def _lpm_loyalty_policy_partner(self):
        self.ensure_one()
        return self.commercial_partner_id or self

    def _lpm_can_earn_points(self):
        self.ensure_one()
        policy_partner = self._lpm_loyalty_policy_partner()
        allowed = bool(policy_partner.lpm_can_earn_loyalty_points)
        self._lpm_log_loyalty_policy_decision("earn", allowed, policy_partner=policy_partner)
        return allowed

    def _lpm_can_redeem_points(self):
        self.ensure_one()
        policy_partner = self._lpm_loyalty_policy_partner()
        allowed = bool(policy_partner.lpm_can_redeem_loyalty_points)
        self._lpm_log_loyalty_policy_decision("redeem", allowed, policy_partner=policy_partner)
        return allowed

    def _lpm_log_loyalty_policy_decision(self, action, allowed, policy_partner=None, source=None):
        self.ensure_one()
        policy_partner = policy_partner or self._lpm_loyalty_policy_partner()
        _logger.info(
            "%s DECISION | action=%s | allowed=%s | partner=%s | partner_id=%s "
            "| policy_partner=%s | policy_partner_id=%s | source=%s",
            _PARTNER_HEAD,
            action,
            allowed,
            self.display_name,
            self.id,
            policy_partner.display_name,
            policy_partner.id,
            source or "unspecified",
        )
