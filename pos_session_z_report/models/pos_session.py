# -*- coding: utf-8 -*-

from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def action_open_z_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Z-Report',
            'res_model': 'pos.session.z.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }
