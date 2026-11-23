from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import AccessError, UserError, MissingError
from odoo.http import request


class AlarmSource(http.Controller):
    @http.route('/native_alarm/<int:alarm_id>/source', type='http', auth='user', methods=['GET'])
    def open_source(self, alarm_id, **kwargs):
        alarm = request.env['native.alarm'].browse(alarm_id).exists()
        if not alarm:
            raise request.not_found()
        try:
            action = alarm.action_open_record()
        except (AccessError, UserError, MissingError):
            raise request.not_found()
        response = request.redirect('/web#' + urlencode({
            'id': action['res_id'], 'model': action['res_model'], 'view_type': 'form',
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
