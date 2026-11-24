from odoo import api, models, _
from odoo.exceptions import UserError
from odoo.addons.native_alarm.models.instrumentation import logged_operation


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    @logged_operation('PURCHASE_ARRIVAL_ENABLE')
    def _enable_arrival_alarm_target(self):
        targets = self.env['native.alarm.target']
        model = self.env['ir.model']._get('purchase.order')
        if not targets.search([('model_id', '=', model.id)], limit=1):
            targets.create({'model_id': model.id})

    def _arrival_alarm_eligible(self):
        self.ensure_one()
        return (self.state in ('purchase', 'done') and bool(self.date_planned)
                and self.receipt_status != 'full')

    @logged_operation('PURCHASE_ARRIVAL_OPEN')
    def action_set_arrival_alarm(self):
        self.ensure_one()
        self.check_access('read')
        if not self._arrival_alarm_eligible():
            raise UserError(_('A confirmed order with an expected arrival and an outstanding receipt is required.'))
        action = self.env['native.alarm'].action_from_record(self._name, self.ids)
        action['context'].update(
            default_name=_('Expected arrival: %(order)s — %(vendor)s',
                           order=self.name, vendor=self.partner_id.display_name),
            default_alarm_at=self.date_planned,
            default_purchase_arrival_date=self.date_planned,
            default_purchase_arrival_tracking=True,
        )
        return action
