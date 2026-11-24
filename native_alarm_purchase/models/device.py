from odoo import models


class AlarmDevice(models.Model):
    _inherit = 'native.alarm.device'

    def companion_sync(self, responses=None):
        self._authorize_companion()
        alarms = self.env['native.alarm'].sudo().with_company(self.company_id).search([
            ('device_id', '=', self.id), ('company_id', '=', self.company_id.id),
            ('user_id', 'in', self.allowed_user_ids.ids), ('state', '=', 'scheduled'),
            ('delivery', 'in', ['device', 'both']), ('purchase_arrival_tracking', '=', True),
        ])
        alarms._sync_purchase_arrivals()
        return super().companion_sync(responses)
