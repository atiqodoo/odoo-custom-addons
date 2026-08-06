# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger("pos_direct_thermal_printer.res_config_settings")


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    dtrp_enabled = fields.Boolean(related="pos_config_id.dtrp_enabled", readonly=False)
    dtrp_auto_print_on_validate = fields.Boolean(
        related="pos_config_id.dtrp_auto_print_on_validate",
        readonly=False,
    )
    dtrp_skip_receipt_screen = fields.Boolean(
        related="pos_config_id.dtrp_skip_receipt_screen",
        readonly=False,
    )
    dtrp_connection_mode = fields.Selection(
        related="pos_config_id.dtrp_connection_mode",
        readonly=False,
    )
    dtrp_bridge_url = fields.Char(related="pos_config_id.dtrp_bridge_url", readonly=False)
    dtrp_bridge_token = fields.Char(related="pos_config_id.dtrp_bridge_token", readonly=False)
    dtrp_printer_identifier = fields.Char(
        related="pos_config_id.dtrp_printer_identifier",
        readonly=False,
    )
    dtrp_paper_width = fields.Selection(related="pos_config_id.dtrp_paper_width", readonly=False)
    dtrp_codepage = fields.Selection(related="pos_config_id.dtrp_codepage", readonly=False)
    dtrp_receipt_profile = fields.Selection(
        related="pos_config_id.dtrp_receipt_profile",
        readonly=False,
    )
    dtrp_receipt_copies = fields.Integer(
        related="pos_config_id.dtrp_receipt_copies",
        readonly=False,
    )
    dtrp_cut_paper = fields.Boolean(related="pos_config_id.dtrp_cut_paper", readonly=False)
    dtrp_open_cash_drawer = fields.Boolean(
        related="pos_config_id.dtrp_open_cash_drawer",
        readonly=False,
    )
    dtrp_print_customer = fields.Boolean(
        related="pos_config_id.dtrp_print_customer",
        readonly=False,
    )
    dtrp_receipt_metadata_template = fields.Text(
        related="pos_config_id.dtrp_receipt_metadata_template",
        readonly=False,
    )
    dtrp_move_negative_adjustments_to_payments = fields.Boolean(
        related="pos_config_id.dtrp_move_negative_adjustments_to_payments",
        readonly=False,
    )
    dtrp_print_loyalty_transaction = fields.Boolean(
        related="pos_config_id.dtrp_print_loyalty_transaction",
        readonly=False,
    )
    dtrp_terms_conditions = fields.Char(
        related="pos_config_id.dtrp_terms_conditions",
        readonly=False,
    )
    dtrp_bottom_feed_lines = fields.Integer(
        related="pos_config_id.dtrp_bottom_feed_lines",
        readonly=False,
    )
    dtrp_timeout_ms = fields.Integer(related="pos_config_id.dtrp_timeout_ms", readonly=False)
    dtrp_retry_count = fields.Integer(related="pos_config_id.dtrp_retry_count", readonly=False)
    dtrp_show_error_popup = fields.Boolean(
        related="pos_config_id.dtrp_show_error_popup",
        readonly=False,
    )
    dtrp_fallback_to_receipt_screen = fields.Boolean(
        related="pos_config_id.dtrp_fallback_to_receipt_screen",
        readonly=False,
    )
    dtrp_debug_logging = fields.Boolean(
        related="pos_config_id.dtrp_debug_logging",
        readonly=False,
    )

    def set_values(self):
        for settings in self:
            if settings.pos_config_id:
                _logger.info(
                    "[DTRP][settings] Saving direct printer settings for POS config '%s' "
                    "(id=%s): enabled=%s mode=%s bridge_url=%s printer=%s paper=%s "
                    "auto=%s skip=%s copies=%s cut=%s drawer=%s move_adjustments=%s "
                    "loyalty_footer=%s bottom_feed=%s timeout=%s retries=%s debug=%s",
                    settings.pos_config_id.name,
                    settings.pos_config_id.id,
                    settings.dtrp_enabled,
                    settings.dtrp_connection_mode,
                    settings.dtrp_bridge_url,
                    settings.dtrp_printer_identifier,
                    settings.dtrp_paper_width,
                    settings.dtrp_auto_print_on_validate,
                    settings.dtrp_skip_receipt_screen,
                    settings.dtrp_receipt_copies,
                    settings.dtrp_cut_paper,
                    settings.dtrp_open_cash_drawer,
                    settings.dtrp_move_negative_adjustments_to_payments,
                    settings.dtrp_print_loyalty_transaction,
                    settings.dtrp_bottom_feed_lines,
                    settings.dtrp_timeout_ms,
                    settings.dtrp_retry_count,
                    settings.dtrp_debug_logging,
                )
        return super().set_values()
