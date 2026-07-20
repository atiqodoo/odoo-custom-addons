# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class PosConfig(models.Model):
    """Set the lock and time limit for the session lock configuration"""
    _inherit = 'pos.config'

    pos_lock = fields.Boolean(string='Enable Lock Screen',
                              help='Lock Screen')
    idle_time_limit = fields.Integer(string="Idle time limit(In minutes)",
                                     default=10,
                                     help='Time limit in minutes and seconds')
    backend_app_gate_lock_time_limit = fields.Integer(
        string="Backend app gate time limit(In minutes)",
        default=0,
        help=(
            "Time in minutes before backend App Gate and M-Pesa SMS app "
            "authorizations expire. Leave empty or 0 to keep the current "
            "browser session behavior."
        ),
    )

    @api.model
    def sbl_get_backend_gate_lock_minutes(self):
        config = self.env['pos.config'].sudo().search([
            ('pos_lock', '=', True),
            ('current_session_id', '!=', False),
        ], limit=1)
        if not config:
            config = self.env['pos.config'].sudo().search([
                ('pos_lock', '=', True),
                ('backend_app_gate_lock_time_limit', '>', 0),
            ], limit=1)
        return {
            'minutes': int(config.backend_app_gate_lock_time_limit or 0) if config else 0,
            'config_id': config.id if config else False,
        }
