# -*- coding: utf-8 -*-
import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    modern_quotation_default_draft_partner_id = fields.Many2one(
        'res.partner',
        string='Default Draft Quotation Customer',
        config_parameter='modern_quotation_catalogue.default_draft_partner_id',
        domain="[('customer_rank', '>', 0)]",
        help='Customer used when a Modern Quotation is created before the user selects a customer.',
    )

    def set_values(self):
        result = super().set_values()
        _logger.info(
            '%s | SETTINGS UPDATED | default_draft_partner_id=%s',
            'MODERN QUOTATION CATALOGUE',
            self.modern_quotation_default_draft_partner_id.id,
        )
        return result
