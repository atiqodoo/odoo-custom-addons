import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


_logger = logging.getLogger(__name__)
WAIVER_TYPES = [
    ('invoice_variance', 'Invoice Variance'),
    ('price_discrepancy', 'Price Discrepancy'),
    ('supplier_delay', 'Supplier Delay'),
    ('other', 'Other'),
]


class VendorPaymentAuditFinding(models.Model):
    _name = 'vendor.payment.audit.finding'
    _description = 'Vendor Payment Audit Finding'
    _inherit = ['mail.thread']
    _order = 'requires_payment_block desc, severity desc, id desc'

    name = fields.Char(required=True)
    case_id = fields.Many2one(
        'vendor.payment.audit.case',
        required=True,
        ondelete='cascade',
        index=True,
    )
    bill_id = fields.Many2one(
        'account.move',
        related='case_id.bill_id',
        store=True,
        readonly=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        related='case_id.vendor_id',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='case_id.company_id',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='case_id.currency_id',
        store=True,
        readonly=True,
    )
    variance_type_id = fields.Many2one(
        'vendor.payment.audit.variance.type',
        required=True,
        ondelete='restrict',
        index=True,
    )
    severity = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        required=True,
        default='medium',
        tracking=True,
    )
    source_code = fields.Char(required=True, index=True)
    source_model = fields.Char(index=True)
    source_record_id = fields.Integer(index=True)
    source_key = fields.Char(required=True, index=True)
    product_id = fields.Many2one('product.product')
    invoice_line_id = fields.Many2one('account.move.line')
    expected_amount = fields.Monetary(currency_field='currency_id')
    actual_amount = fields.Monetary(currency_field='currency_id')
    variance_amount = fields.Monetary(currency_field='currency_id')
    variance_percent = fields.Float()
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('resolved', 'Resolved'),
            ('waived', 'Waived'),
            ('obsolete', 'Obsolete'),
        ],
        default='open',
        required=True,
        tracking=True,
    )
    requires_payment_block = fields.Boolean(default=False, tracking=True)
    policy_line_id = fields.Many2one('vendor.payment.audit.policy.line', readonly=True)
    resolution_requirement = fields.Selection(
        related='policy_line_id.resolution_requirement',
        readonly=True,
    )
    block_reason = fields.Char(readonly=True)
    debug_payload_json = fields.Text(readonly=True)
    resolved_by_id = fields.Many2one('res.users', readonly=True)
    resolved_at = fields.Datetime(readonly=True)
    waived_by_id = fields.Many2one('res.users', readonly=True)
    waived_at = fields.Datetime(readonly=True)
    waiver_reason = fields.Text()
    waiver_type = fields.Selection(WAIVER_TYPES, string='Waiver Type', copy=False, tracking=True)
    credit_note_id = fields.Many2one(
        'account.move',
        domain="[('move_type', '=', 'in_refund'), ('state', '=', 'posted'), ('partner_id', '=', vendor_id)]",
    )
    matched_credit_note_amount = fields.Monetary(
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    remaining_resolution_amount = fields.Monetary(
        currency_field='currency_id',
        readonly=True,
        copy=False,
    )
    resolution_tolerance_amount = fields.Monetary(
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Amount that may remain after credit note resolution, usually from the source variance policy.',
    )
    case_state = fields.Selection(
        related='case_id.state',
        string='Audit Status',
        store=True,
        readonly=True,
    )

    _sql_constraints = [
        ('case_source_key_unique', 'unique(case_id, source_key)', 'Finding source must be unique per audit case.'),
    ]

    def action_mark_resolved(self):
        for finding in self:
            if finding.policy_line_id.resolution_requirement in ('credit_note', 'credit_note_or_waiver') and not finding.credit_note_id:
                raise ValidationError(_('A posted vendor credit note is required before this finding can be resolved.'))
            finding.write({
                'state': 'resolved',
                'requires_payment_block': False,
                'remaining_resolution_amount': 0.0,
                'resolved_by_id': self.env.user.id,
                'resolved_at': fields.Datetime.now(),
            })
            _logger.info(
                '[VPA_RESOLUTION] resolved finding_id=%s bill_id=%s credit_note_id=%s user_id=%s',
                finding.id,
                finding.bill_id.id,
                finding.credit_note_id.id,
                self.env.user.id,
            )
        return True

    def action_open_bill(self):
        self.ensure_one()
        _logger.info(
            '[VPA_FINDING_OPEN_BILL][START] finding_id=%s bill_id=%s user_id=%s',
            self.id,
            self.bill_id.id,
            self.env.user.id,
        )
        if not self.bill_id:
            _logger.warning(
                '[VPA_FINDING_OPEN_BILL][ERROR] finding_id=%s reason=missing_bill user_id=%s',
                self.id,
                self.env.user.id,
            )
            return {'type': 'ir.actions.act_window_close'}
        _logger.info(
            '[VPA_FINDING_OPEN_BILL][END] finding_id=%s bill_id=%s',
            self.id,
            self.bill_id.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Bill'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.bill_id.id,
            'target': 'current',
        }

    def action_open_case(self):
        self.ensure_one()
        _logger.info(
            '[VPA_FINDING_OPEN_CASE][START] finding_id=%s case_id=%s user_id=%s',
            self.id,
            self.case_id.id,
            self.env.user.id,
        )
        if not self.case_id:
            _logger.warning(
                '[VPA_FINDING_OPEN_CASE][ERROR] finding_id=%s reason=missing_case user_id=%s',
                self.id,
                self.env.user.id,
            )
            return {'type': 'ir.actions.act_window_close'}
        _logger.info(
            '[VPA_FINDING_OPEN_CASE][END] finding_id=%s case_id=%s',
            self.id,
            self.case_id.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Payment Audit Case'),
            'res_model': 'vendor.payment.audit.case',
            'view_mode': 'form',
            'res_id': self.case_id.id,
            'target': 'current',
        }

    def action_open_source(self):
        self.ensure_one()
        _logger.info(
            '[VPA_FINDING_OPEN_SOURCE][START] finding_id=%s source_model=%s source_record_id=%s user_id=%s',
            self.id,
            self.source_model,
            self.source_record_id,
            self.env.user.id,
        )
        if not self.source_model or not self.source_record_id or self.source_model not in self.env:
            _logger.warning(
                '[VPA_FINDING_OPEN_SOURCE][ERROR] finding_id=%s source_model=%s source_record_id=%s reason=missing_source',
                self.id,
                self.source_model,
                self.source_record_id,
            )
            return {'type': 'ir.actions.act_window_close'}
        source = self.env[self.source_model].browse(self.source_record_id).exists()
        if not source:
            _logger.warning(
                '[VPA_FINDING_OPEN_SOURCE][ERROR] finding_id=%s source_model=%s source_record_id=%s reason=not_found',
                self.id,
                self.source_model,
                self.source_record_id,
            )
            return {'type': 'ir.actions.act_window_close'}
        _logger.info(
            '[VPA_FINDING_OPEN_SOURCE][END] finding_id=%s source_model=%s source_record_id=%s',
            self.id,
            self.source_model,
            self.source_record_id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Audit Source'),
            'res_model': self.source_model,
            'view_mode': 'form',
            'res_id': source.id,
            'target': 'current',
        }

    def action_waive(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Waive Payment Audit Finding'),
            'res_model': 'vendor.payment.audit.waiver.wizard', 'view_mode': 'form',
            'target': 'new', 'context': {'default_case_id': self.case_id.id, 'default_finding_id': self.id},
        }

    def _approve_waiver(self, waiver_type, reason):
        self.ensure_one()
        if self.state != 'open' or not self.requires_payment_block:
            raise ValidationError(_('Only an active blocking finding can be waived.'))
        groups = self.policy_line_id.approval_group_ids
        if not (self.env.user.has_group('vendor_payment_auditing.group_vendor_payment_audit_manager')
                or bool(groups & self.env.user.groups_id)):
            raise AccessError(_('You are not allowed to waive this finding.'))
        if waiver_type not in dict(self._fields['waiver_type'].selection) or not (reason or '').strip():
            raise ValidationError(_('Select a waiver type and enter a reason.'))
        _logger.info('[VPA][WAIVER][START] finding_id=%s bill_id=%s user_id=%s', self.id, self.bill_id.id, self.env.uid)
        super(VendorPaymentAuditFinding, self).write({
            'state': 'waived', 'requires_payment_block': False, 'waiver_type': waiver_type,
            'waiver_reason': reason.strip(), 'waived_by_id': self.env.uid,
            'waived_at': fields.Datetime.now(),
        })
        _logger.info('[VPA][WAIVER][END] finding_id=%s bill_id=%s user_id=%s', self.id, self.bill_id.id, self.env.uid)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'waiver_type', 'waiver_reason', 'waived_by_id', 'waived_at'}
        if any(protected.intersection(vals) or vals.get('state') == 'waived' for vals in vals_list):
            raise AccessError(_('Waiver details can only be recorded through the approval workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'waiver_type', 'waiver_reason', 'waived_by_id', 'waived_at'}
        if protected.intersection(vals) or vals.get('state') == 'waived':
            raise AccessError(_('Waiver details can only be recorded through the approval workflow.'))
        return super().write(vals)

    @staticmethod
    def dumps_payload(payload):
        try:
            return json.dumps(payload or {}, sort_keys=True, default=str)
        except TypeError:
            return json.dumps({'raw': str(payload)}, sort_keys=True)
