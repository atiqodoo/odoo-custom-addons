import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)


class VendorPaymentAuditCase(models.Model):
    _name = 'vendor.payment.audit.case'
    _description = 'Vendor Payment Audit Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_scan_at desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    bill_id = fields.Many2one(
        'account.move',
        required=True,
        ondelete='cascade',
        index=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        related='bill_id.partner_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='bill_id.company_id',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='bill_id.currency_id',
        store=True,
        readonly=True,
    )
    policy_id = fields.Many2one(
        'vendor.payment.audit.policy',
        string='Applied Policy',
        readonly=True,
        copy=False,
    )
    finding_ids = fields.One2many(
        'vendor.payment.audit.finding',
        'case_id',
        string='Findings',
        copy=False,
    )
    state = fields.Selection(
        [
            ('clear', 'Clear'),
            ('review', 'Review'),
            ('blocked', 'Payment Blocked'),
            ('resolved', 'Resolved'),
            ('waived', 'Waived'),
        ],
        compute='_compute_state',
        store=True,
        tracking=True,
    )
    payment_blocked = fields.Boolean(compute='_compute_state', store=True)
    blocking_finding_count = fields.Integer(compute='_compute_state', store=True)
    open_finding_count = fields.Integer(compute='_compute_state', store=True)
    block_reason_summary = fields.Text(compute='_compute_state', store=True)
    last_scan_at = fields.Datetime(readonly=True, copy=False)
    last_policy_eval_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ('bill_unique', 'unique(bill_id)', 'Only one payment audit case is allowed per bill.'),
    ]

    @api.depends('bill_id.name')
    def _compute_name(self):
        for case in self:
            case.name = _('Payment Audit: %s') % (case.bill_id.display_name or case.bill_id.name or case.bill_id.id)

    @api.depends(
        'finding_ids.state',
        'finding_ids.requires_payment_block',
        'finding_ids.block_reason',
    )
    def _compute_state(self):
        for case in self:
            active = case.finding_ids.filtered(lambda finding: finding.state == 'open')
            blockers = active.filtered('requires_payment_block')
            case.open_finding_count = len(active)
            case.blocking_finding_count = len(blockers)
            case.payment_blocked = bool(blockers)
            case.block_reason_summary = '\n'.join(blockers.mapped('block_reason'))
            if blockers:
                case.state = 'blocked'
            elif active:
                case.state = 'review'
            elif case.finding_ids.filtered(lambda finding: finding.state == 'waived'):
                case.state = 'waived'
            elif case.finding_ids:
                case.state = 'resolved'
            else:
                case.state = 'clear'

    def action_scan(self):
        for case in self:
            case.bill_id._vendor_payment_audit_scan()
        return True

    def action_approve_waiver(self):
        for case in self:
            case._check_waiver_access()
            blockers = case.finding_ids.filtered(
                lambda finding: finding.state == 'open' and finding.requires_payment_block
            )
            if not blockers:
                raise ValidationError(_('There are no blocking findings to waive.'))
            blockers.action_waive()
            _logger.warning(
                '[VPA_WAIVER] case_id=%s bill_id=%s finding_ids=%s approver_id=%s',
                case.id,
                case.bill_id.id,
                blockers.ids,
                self.env.user.id,
            )
        return True

    def _check_waiver_access(self):
        self.ensure_one()
        if self.env.user.has_group('vendor_payment_auditing.group_vendor_payment_audit_manager'):
            return True
        groups = self.finding_ids.mapped('policy_line_id.approval_group_ids')
        for group in groups:
            xml_id = group.get_xml_id().get(group.id)
            if xml_id and self.env.user.has_group(xml_id):
                return True
        raise AccessError(_('You are not allowed to waive vendor payment audit findings.'))
