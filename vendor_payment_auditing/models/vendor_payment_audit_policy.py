import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class VendorPaymentAuditPolicy(models.Model):
    _name = 'vendor.payment.audit.policy'
    _description = 'Vendor Payment Audit Policy'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )
    default_behavior = fields.Selection(
        [
            ('allow', 'Allow if No Matching Rule'),
            ('block', 'Block if No Matching Rule'),
        ],
        default='allow',
        required=True,
    )
    line_ids = fields.One2many(
        'vendor.payment.audit.policy.line',
        'policy_id',
        string='Rules',
        copy=True,
    )
    notes = fields.Text()

    def _get_matching_line(self, finding):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda line: line.active and line.applies_to_finding(finding))
        line = lines[:1]
        _logger.debug(
            '[VPA_POLICY] match policy_id=%s finding_id=%s line_id=%s default_behavior=%s',
            self.id,
            finding.id,
            line.id if line else False,
            self.default_behavior,
        )
        return line


class VendorPaymentAuditPolicyLine(models.Model):
    _name = 'vendor.payment.audit.policy.line'
    _description = 'Vendor Payment Audit Policy Rule'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    policy_id = fields.Many2one(
        'vendor.payment.audit.policy',
        required=True,
        ondelete='cascade',
    )
    variance_type_id = fields.Many2one(
        'vendor.payment.audit.variance.type',
        required=True,
        ondelete='restrict',
    )
    severity_min = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        default='low',
        required=True,
    )
    tolerance_amount = fields.Monetary(
        currency_field='currency_id',
        help='Only block when the absolute variance amount is above this value.',
    )
    tolerance_percent = fields.Float(
        help='Only block when the absolute variance percent is above this value.',
    )
    action = fields.Selection(
        [
            ('allow', 'Allow Payment'),
            ('block', 'Block Payment'),
            ('review', 'Require Review Only'),
        ],
        default='block',
        required=True,
    )
    resolution_requirement = fields.Selection(
        [
            ('none', 'No Procedure Required'),
            ('credit_note', 'Vendor Credit Note Required'),
            ('source_resolved', 'Source Finding Must Be Resolved'),
            ('supporting_document', 'Supporting Document Required'),
            ('manager_approval', 'Manager Approval Required'),
            ('credit_note_or_waiver', 'Vendor Credit Note or Authorized Waiver'),
        ],
        default='credit_note_or_waiver',
        required=True,
    )
    approval_group_ids = fields.Many2many(
        'res.groups',
        string='Waiver Approval Groups',
        help='If empty, Vendor Payment Audit Managers can approve waivers.',
    )
    currency_id = fields.Many2one(
        related='policy_id.company_id.currency_id',
        store=True,
        readonly=True,
    )

    @api.constrains('tolerance_amount', 'tolerance_percent')
    def _check_tolerances(self):
        for line in self:
            if line.tolerance_amount < 0 or line.tolerance_percent < 0:
                raise ValidationError(_('Tolerance values cannot be negative.'))

    def applies_to_finding(self, finding):
        self.ensure_one()
        severity_rank = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
        if self.variance_type_id != finding.variance_type_id:
            return False
        if severity_rank.get(finding.severity, 0) < severity_rank.get(self.severity_min, 1):
            return False
        amount = abs(finding.variance_amount or 0.0)
        percent = abs(finding.variance_percent or 0.0)
        checks = []
        if self.tolerance_amount:
            checks.append(amount > self.tolerance_amount)
        if self.tolerance_percent:
            checks.append(percent > self.tolerance_percent)
        if checks:
            return any(checks)
        return bool(amount or percent)
