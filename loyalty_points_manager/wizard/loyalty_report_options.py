import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class LoyaltyReportOptions(models.TransientModel):
    _name = "loyalty.report.options"
    _description = "Loyalty Report Options"

    report_type = fields.Selection([("customers", "Customer Summary"), ("movements", "Point Movements")],
                                   default="customers", required=True)
    date_from = fields.Date(string="Period From", default=lambda self: self.env.context.get("lpm_date_from"))
    date_to = fields.Date(string="Period To", default=lambda self: self.env.context.get("lpm_date_to")
                          or fields.Date.context_today(self), required=True)
    as_of = fields.Date(string="Balance As Of", default=lambda self: self.env.context.get("lpm_as_of")
                        or fields.Date.context_today(self), required=True)
    dormant_days = fields.Integer(string="Inactivity Threshold (Days)",
        default=lambda self: self.env.context.get("lpm_dormant_days", 0),
        help="Zero disables the dormant filter. Set the number of days since the last qualifying purchase.")

    def action_open_report(self):
        self.ensure_one()
        self.check_access("read")
        if not self.env.user.has_group("loyalty_points_manager.group_loyalty_auditor"):
            raise AccessError(_("Loyalty Audit access is required."))
        _logger.debug("[LPM][REPORT_OPTIONS][START] user_id=%s report=%s", self.env.uid, self.report_type)
        context = dict(self.env.context, lpm_date_from=fields.Date.to_string(self.date_from),
                       lpm_date_to=fields.Date.to_string(self.date_to),
                       lpm_as_of=fields.Date.to_string(self.as_of), lpm_dormant_days=self.dormant_days)
        try:
            self.env["loyalty.report.service"].with_context(context)._parameters()
            actions = {"customers": "loyalty_points_manager.action_loyalty_customer_report",
                       "movements": "loyalty_points_manager.action_loyalty_movement_report"}
            action = self.env["ir.actions.actions"]._for_xml_id(actions[self.report_type])
            action["context"] = context
        except Exception:
            _logger.exception("[LPM][REPORT_OPTIONS][ERROR] user_id=%s report=%s", self.env.uid, self.report_type)
            raise
        _logger.debug("[LPM][REPORT_OPTIONS][END] user_id=%s report=%s", self.env.uid, self.report_type)
        return action
