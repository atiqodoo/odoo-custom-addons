from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _native_alarm_is_active(self):
        self.ensure_one()
        return self.state in ('draft', 'sent')
