# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger("pos_direct_thermal_printer.pos_config")

DEFAULT_RECEIPT_METADATA_TEMPLATE = """{company_name}
{street}
{street2}
{city}
{phone}
{email}
{website}
VAT: {vat}"""


class PosConfig(models.Model):
    _inherit = "pos.config"

    dtrp_enabled = fields.Boolean(
        string="Direct Thermal Printer",
        default=False,
        help="Enable direct ESC/POS thermal receipt printing for this POS.",
    )
    dtrp_auto_print_on_validate = fields.Boolean(
        string="Auto Print on Validate",
        default=True,
        help="Print immediately after the POS order is validated.",
    )
    dtrp_skip_receipt_screen = fields.Boolean(
        string="Skip Receipt Preview",
        default=True,
        help="Return to the product screen after direct printing instead of opening the receipt screen.",
    )
    dtrp_connection_mode = fields.Selection(
        [
            ("odoo_server_windows", "Odoo Server Windows RAW"),
            ("local_bridge", "Local Print Bridge"),
            ("web_serial", "Browser Web Serial"),
        ],
        string="Connection Mode",
        default="odoo_server_windows",
        required=True,
        help="How the POS browser sends ESC/POS bytes to the printer.",
    )
    dtrp_bridge_url = fields.Char(
        string="Local Bridge URL",
        default="http://127.0.0.1:9109",
        help="Local print bridge endpoint. The module posts print jobs to this URL.",
    )
    dtrp_bridge_token = fields.Char(
        string="Bridge Token",
        help="Optional token sent to the local bridge as X-Odoo-Print-Token.",
    )
    dtrp_printer_identifier = fields.Char(
        string="Printer Identifier",
        help="Optional printer name, USB identifier, or bridge-side alias.",
    )
    dtrp_paper_width = fields.Selection(
        [("58", "58 mm"), ("80", "80 mm")],
        string="Paper Width",
        default="80",
        required=True,
    )
    dtrp_codepage = fields.Selection(
        [
            ("cp437", "CP437"),
            ("cp850", "CP850"),
            ("ascii", "ASCII"),
        ],
        string="Codepage",
        default="cp437",
        required=True,
    )
    dtrp_receipt_profile = fields.Selection(
        [
            ("generic", "Generic ESC/POS"),
            ("xpos_k260l", "X-POS K260L"),
        ],
        string="Receipt Profile",
        default="generic",
        required=True,
    )
    dtrp_receipt_copies = fields.Integer(
        string="Receipt Copies",
        default=1,
        help="Number of copies to print after validation.",
    )
    dtrp_cut_paper = fields.Boolean(string="Cut Paper", default=True)
    dtrp_open_cash_drawer = fields.Boolean(string="Open Cash Drawer", default=False)
    dtrp_print_customer = fields.Boolean(string="Print Customer", default=True)
    dtrp_receipt_metadata_template = fields.Text(
        string="Receipt Metadata Template",
        default=DEFAULT_RECEIPT_METADATA_TEMPLATE,
        help=(
            "Per-shop receipt header metadata template. One line per printed line. "
            "Available placeholders: {company_name}, {street}, {street2}, {city}, "
            "{phone}, {email}, {website}, {vat}, {pos_name}, {order_name}, {date}, "
            "{cashier}, {customer}. Lines that render empty or false are skipped."
        ),
    )
    dtrp_move_negative_adjustments_to_payments = fields.Boolean(
        string="Show Discounts in Payment Lines",
        default=True,
        help=(
            "Move negative loyalty, gift card, and global discount lines out of the "
            "product list and print them with the payment method display lines."
        ),
    )
    dtrp_print_loyalty_transaction = fields.Boolean(
        string="Print Loyalty Transaction",
        default=False,
        help="Print loyalty card activity at the bottom of the thermal receipt.",
    )
    dtrp_terms_conditions = fields.Char(
        string="Receipt Terms and Conditions",
        help="Optional terms and conditions printed at the very bottom of the receipt.",
    )
    dtrp_bottom_feed_lines = fields.Integer(
        string="Bottom Feed Lines",
        default=6,
        help="Blank lines fed after the footer before cutting. Increase if the cutter trims payment lines.",
    )
    dtrp_timeout_ms = fields.Integer(string="Timeout (ms)", default=8000)
    dtrp_retry_count = fields.Integer(string="Retry Count", default=1)
    dtrp_show_error_popup = fields.Boolean(string="Show Error Popup", default=True)
    dtrp_fallback_to_receipt_screen = fields.Boolean(
        string="Fallback to Receipt Screen",
        default=False,
        help="Open the standard receipt screen if direct printing fails.",
    )
    dtrp_debug_logging = fields.Boolean(
        string="Debug Logging",
        default=True,
        help="Enable detailed POS console logs and backend diagnostics logs.",
    )

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            UPDATE pos_config
               SET dtrp_receipt_metadata_template = %s
             WHERE dtrp_receipt_metadata_template IS NULL
                OR dtrp_receipt_metadata_template = ''
            """,
            [DEFAULT_RECEIPT_METADATA_TEMPLATE],
        )
        self.env.cr.execute(
            """
            UPDATE pos_config
               SET dtrp_bottom_feed_lines = 6
             WHERE dtrp_bottom_feed_lines IS NULL
            """
        )

    @api.constrains(
        "dtrp_receipt_copies",
        "dtrp_timeout_ms",
        "dtrp_retry_count",
        "dtrp_bottom_feed_lines",
    )
    def _check_direct_printer_numbers(self):
        for config in self:
            vals = {}
            if config.dtrp_receipt_copies < 1:
                vals["dtrp_receipt_copies"] = 1
            if config.dtrp_timeout_ms < 1000:
                vals["dtrp_timeout_ms"] = 1000
            if config.dtrp_retry_count < 0:
                vals["dtrp_retry_count"] = 0
            if config.dtrp_bottom_feed_lines < 0:
                vals["dtrp_bottom_feed_lines"] = 0
            if config.dtrp_bottom_feed_lines > 12:
                vals["dtrp_bottom_feed_lines"] = 12
            if vals:
                _logger.warning(
                    "[DTRP][config] Normalizing invalid values for POS config '%s' (id=%s): %s",
                    config.name,
                    config.id,
                    vals,
                )
                config.write(vals)

    def write(self, vals):
        result = super().write(vals)
        watched = {key for key in vals if key.startswith("dtrp_")}
        if watched:
            for config in self:
                _logger.info(
                    "[DTRP][config] Updated direct printer settings for '%s' (id=%s): %s",
                    config.name,
                    config.id,
                    {key: vals[key] for key in sorted(watched)},
                )
        return result
