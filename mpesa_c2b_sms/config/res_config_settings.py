"""
Adds M-Pesa configuration fields to Odoo General Settings.
All settings stored in ir.config_parameter for easy access everywhere.
"""
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mpesa_api_token = fields.Char(
        'Bridge API Token',
        config_parameter='mpesa_c2b_sms.api_token',
        help='Pre-shared token validated on every bridge POST request.',
    )
    mpesa_amount_tolerance = fields.Float(
        'Amount Tolerance (Ksh)',
        config_parameter='mpesa_c2b_sms.amount_tolerance',
        default=1.0,
        help='Acceptable rounding difference between M-Pesa amount and order total.',
    )
    mpesa_auto_match_partner = fields.Boolean(
        'Auto-match Partner by Phone',
        config_parameter='mpesa_c2b_sms.auto_match_partner',
        default=True,
    )
    mpesa_bridge_type = fields.Selection(
        selection=[('python', 'Python Bridge'), ('go', 'Go Bridge')],
        string='Bridge Engine',
        config_parameter='mpesa_c2b_sms.bridge_type',
        default='python',
        help='Choose which local bridge service the SMS app controls.',
    )
    mpesa_bridge_runner_path = fields.Char(
        'Python Bridge Runner Path',
        config_parameter='mpesa_c2b_sms.bridge_runner_path',
        default=r'C:\odoo18\mpesa_sms_bridge\run_bridge.ps1',
        help='PowerShell runner used when Python Bridge is selected.',
    )
    mpesa_go_bridge_runner_path = fields.Char(
        'Go Bridge Runner Path',
        config_parameter='mpesa_c2b_sms.go_bridge_runner_path',
        default=r'C:\odoo18\mpesa_sms_bridge_go\run_bridge.ps1',
        help='PowerShell runner used when Go Bridge is selected.',
    )

    @api.model
    def get_mpesa_param(self, key: str, default=None):
        """Convenience accessor for other modules."""
        val = self.env['ir.config_parameter'].sudo().get_param(
            f'mpesa_c2b_sms.{key}'
        )
        return val if val is not None else default
