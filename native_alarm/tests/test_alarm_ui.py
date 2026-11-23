import json

from odoo.tests import HttpCase, tagged
from odoo.addons.web.controllers.utils import clean_action


@tagged('post_install', '-at_install')
class TestNativeAlarmDialog(HttpCase):
    def test_new_alarm_dialog_renders_linked_record(self):
        partner = self.env['res.partner'].create({'name': 'Alarm dialog rendering target'})
        self.env['native.alarm.target'].create({
            'model_id': self.env['ir.model']._get_id('res.partner'),
        })
        user_model = self.env['native.alarm'].with_user(self.env.ref('base.user_admin'))
        action = clean_action(user_model.action_from_record('res.partner', partner.ids), user_model.env)
        self.browser_js(
            '/web?debug=1',
            '''(async () => {
                const services = odoo.__WOWL_DEBUG__.root.env.services;
                await services.action.doAction(%s);
                await new Promise(requestAnimationFrame);
                const form = document.querySelector('.modal .o_form_view');
                if (!form) { throw new Error('Set Alarm dialog did not render'); }
                const model = form.querySelector('.o_field_widget[name="res_model"]');
                const record = form.querySelector('.o_field_widget[name="res_id"]');
                if (!model || !model.textContent.includes('res.partner')) {
                    throw new Error('Linked record model was not initialized');
                }
                if (!record || !record.textContent.includes('%s')) {
                    throw new Error('Linked record ID was not displayed');
                }
                console.log('test successful');
            })();''' % (json.dumps(action), partner.id),
            ready='Boolean(odoo.__WOWL_DEBUG__)', login='admin', timeout=60,
        )
