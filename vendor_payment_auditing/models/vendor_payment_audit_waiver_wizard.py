from odoo import fields, models, _
from odoo.exceptions import ValidationError
from .vendor_payment_audit_finding import WAIVER_TYPES


class VendorPaymentAuditWaiverWizard(models.TransientModel):
    _name = 'vendor.payment.audit.waiver.wizard'
    _description = 'Waive One Vendor Payment Audit Finding'

    case_id = fields.Many2one('vendor.payment.audit.case', required=True, readonly=True)
    finding_id = fields.Many2one(
        'vendor.payment.audit.finding', required=True,
        domain="[('case_id', '=', case_id), ('state', '=', 'open'), ('requires_payment_block', '=', True)]",
    )
    waiver_type = fields.Selection(WAIVER_TYPES, required=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.finding_id.case_id != self.case_id:
            raise ValidationError(_('The selected finding does not belong to this audit case.'))
        self.finding_id._approve_waiver(self.waiver_type, self.reason)
        return {'type': 'ir.actions.act_window_close'}
