from odoo import models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def _native_alarm_is_active(self):
        self.ensure_one()
        return self.active and not self.is_closed
