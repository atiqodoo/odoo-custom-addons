import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    vendor_payment_audit_case_id = fields.One2many(
        'vendor.payment.audit.case',
        'bill_id',
        string='Vendor Payment Audit Case',
        copy=False,
    )
    vendor_payment_audit_blocked = fields.Boolean(
        compute='_compute_vendor_payment_audit_status',
        store=True,
        copy=False,
    )
    vendor_payment_audit_state = fields.Selection(
        [
            ('clear', 'Clear'),
            ('review', 'Review'),
            ('blocked', 'Payment Blocked'),
            ('resolved', 'Resolved'),
            ('waived', 'Waived'),
        ],
        string='Vendor Payment Audit Status',
        compute='_compute_vendor_payment_audit_status',
        store=True,
    )
    vendor_payment_audit_finding_count = fields.Integer(
        compute='_compute_vendor_payment_audit_status',
        store=True,
    )
    vendor_payment_audit_block_reason = fields.Text(
        compute='_compute_vendor_payment_audit_status',
        store=True,
    )

    @api.depends(
        'vendor_payment_audit_case_id.payment_blocked',
        'vendor_payment_audit_case_id.open_finding_count',
        'vendor_payment_audit_case_id.block_reason_summary',
    )
    def _compute_vendor_payment_audit_status(self):
        for move in self:
            case = move.vendor_payment_audit_case_id[:1]
            move.vendor_payment_audit_blocked = bool(case.payment_blocked)
            move.vendor_payment_audit_state = case.state if case else 'clear'
            move.vendor_payment_audit_finding_count = case.open_finding_count if case else 0
            move.vendor_payment_audit_block_reason = case.block_reason_summary if case else False

    def _vendor_payment_audit_is_bill_candidate(self):
        self.ensure_one()
        return self.move_type == 'in_invoice' and self.state == 'posted'

    def _vendor_payment_audit_get_or_create_case(self):
        self.ensure_one()
        case = self.vendor_payment_audit_case_id[:1]
        if not case:
            case = self.env['vendor.payment.audit.case'].sudo().create({'bill_id': self.id})
            _logger.info('[VPA_SCAN] case_created bill_id=%s case_id=%s', self.id, case.id)
        return case

    def _vendor_payment_audit_get_policy(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id or self.partner_id
        if not partner.vendor_payment_audit_enabled:
            return self.env['vendor.payment.audit.policy'].sudo()
        return partner.vendor_payment_audit_policy_id.sudo()

    def _vendor_payment_audit_scan(self):
        Finding = self.env['vendor.payment.audit.finding'].sudo()
        for move in self:
            if not move._vendor_payment_audit_is_bill_candidate():
                _logger.debug(
                    '[VPA_SCAN] skipped bill_id=%s move_type=%s state=%s',
                    move.id,
                    move.move_type,
                    move.state,
                )
                continue

            case = move._vendor_payment_audit_get_or_create_case().sudo()
            policy = move._vendor_payment_audit_get_policy()
            case.write({
                'policy_id': policy.id if policy else False,
                'last_scan_at': fields.Datetime.now(),
            })

            payloads = move._vendor_payment_audit_collect_findings()
            seen_keys = []
            for payload in payloads:
                source_key = payload['source_key']
                seen_keys.append(source_key)
                values = move._vendor_payment_audit_prepare_finding_values(case, payload)
                existing = case.finding_ids.filtered(lambda finding: finding.source_key == source_key)[:1]
                if existing:
                    if existing.state == 'obsolete':
                        values['state'] = 'open'
                    existing.write(values)
                    finding = existing
                else:
                    finding = Finding.create(values)
                if finding.state in ('resolved', 'waived'):
                    finding.write({'requires_payment_block': False, 'block_reason': False})
                    _logger.debug(
                        '[VPA_POLICY] skipped_resolved bill_id=%s finding_id=%s state=%s',
                        move.id,
                        finding.id,
                        finding.state,
                    )
                    continue
                move._vendor_payment_audit_apply_policy(finding, policy)

            move._vendor_payment_audit_auto_resolve_credit_notes(case)

            stale = case.finding_ids.filtered(
                lambda finding: finding.state == 'open' and finding.source_key not in seen_keys
            )
            if stale:
                stale.write({'state': 'obsolete', 'requires_payment_block': False})
                _logger.info(
                    '[VPA_SCAN] obsolete bill_id=%s case_id=%s finding_ids=%s',
                    move.id,
                    case.id,
                    stale.ids,
                )
            case.write({'last_policy_eval_at': fields.Datetime.now()})
            _logger.info(
                '[VPA_SCAN] completed bill_id=%s case_id=%s findings=%s blocked=%s',
                move.id,
                case.id,
                len(payloads),
                case.payment_blocked,
            )
        return True

    def _vendor_payment_audit_auto_resolve_credit_notes(self, case):
        self.ensure_one()
        credit_note_findings = case.finding_ids.filtered(
            lambda finding: (
                finding.state == 'open'
                and finding.requires_payment_block
                and finding.policy_line_id.resolution_requirement in ('credit_note', 'credit_note_or_waiver')
            )
        )
        if not credit_note_findings:
            return

        credit_notes = self.reversal_move_ids.filtered(
            lambda move: (
                move.move_type == 'in_refund'
                and move.state == 'posted'
                and move.company_id == self.company_id
                and move.partner_id.commercial_partner_id == self.partner_id.commercial_partner_id
            )
        )
        if not credit_notes:
            _logger.debug('[VPA_CREDIT_NOTE] none bill_id=%s case_id=%s', self.id, case.id)
            return

        available_amount = sum(abs(note.amount_total) for note in credit_notes)
        rounding = self.currency_id.rounding or 0.01
        for finding in credit_note_findings:
            required_amount = abs(finding.variance_amount or 0.0)
            if not required_amount:
                continue
            tolerance_amount = max(finding.resolution_tolerance_amount or 0.0, rounding)
            remaining_amount = max(required_amount - available_amount, 0.0)
            if (
                float_compare(available_amount, required_amount, precision_rounding=rounding) >= 0
                or float_compare(available_amount + tolerance_amount, required_amount, precision_rounding=rounding) >= 0
            ):
                finding.write({
                    'state': 'resolved',
                    'requires_payment_block': False,
                    'credit_note_id': credit_notes[:1].id,
                    'matched_credit_note_amount': available_amount,
                    'remaining_resolution_amount': remaining_amount,
                    'block_reason': False,
                    'resolved_by_id': self.env.user.id,
                    'resolved_at': fields.Datetime.now(),
                })
                _logger.info(
                    '[VPA_CREDIT_NOTE] auto_resolved bill_id=%s finding_id=%s credit_note_ids=%s required=%s available=%s remaining=%s tolerance=%s rounding=%s',
                    self.id,
                    finding.id,
                    credit_notes.ids,
                    required_amount,
                    available_amount,
                    remaining_amount,
                    tolerance_amount,
                    rounding,
                )
            else:
                finding.write({
                    'credit_note_id': credit_notes[:1].id,
                    'matched_credit_note_amount': available_amount,
                    'remaining_resolution_amount': remaining_amount,
                    'block_reason': _(
                        '%(variance)s remains blocked: credit note total %(credited).2f does not cover required variance %(required).2f. Remaining %(remaining).2f, allowed remaining %(tolerance).2f.'
                    ) % {
                        'variance': finding.variance_type_id.name,
                        'credited': available_amount,
                        'required': required_amount,
                        'remaining': remaining_amount,
                        'tolerance': tolerance_amount,
                    },
                })
                _logger.info(
                    '[VPA_CREDIT_NOTE] insufficient bill_id=%s finding_id=%s credit_note_ids=%s required=%s available=%s rounding=%s',
                    self.id,
                    finding.id,
                    credit_notes.ids,
                    required_amount,
                    available_amount,
                    rounding,
                )

    def _vendor_payment_audit_prepare_finding_values(self, case, payload):
        self.ensure_one()
        variance_type = self._vendor_payment_audit_get_variance_type(payload['variance_type_code'])
        return {
            'case_id': case.id,
            'name': payload.get('name') or variance_type.name,
            'variance_type_id': variance_type.id,
            'severity': payload.get('severity') or variance_type.default_severity,
            'source_code': payload.get('source_code') or payload['variance_type_code'],
            'source_model': payload.get('source_model'),
            'source_record_id': payload.get('source_record_id') or 0,
            'source_key': payload['source_key'],
            'product_id': payload.get('product_id') or False,
            'invoice_line_id': payload.get('invoice_line_id') or False,
            'expected_amount': payload.get('expected_amount') or 0.0,
            'actual_amount': payload.get('actual_amount') or 0.0,
            'variance_amount': payload.get('variance_amount') or 0.0,
            'variance_percent': payload.get('variance_percent') or 0.0,
            'resolution_tolerance_amount': payload.get('resolution_tolerance_amount') or 0.0,
            'debug_payload_json': self.env['vendor.payment.audit.finding'].dumps_payload(payload.get('debug_payload')),
        }

    def _vendor_payment_audit_get_variance_type(self, code):
        variance_type = self.env['vendor.payment.audit.variance.type'].sudo().search([('code', '=', code)], limit=1)
        if not variance_type:
            variance_type = self.env['vendor.payment.audit.variance.type'].sudo().create({
                'name': code.replace('_', ' ').title(),
                'code': code,
                'default_severity': 'medium',
            })
            _logger.info('[VPA_SOURCE] variance_type_created code=%s id=%s', code, variance_type.id)
        return variance_type

    def _vendor_payment_audit_apply_policy(self, finding, policy):
        self.ensure_one()
        if not policy:
            finding.write({
                'requires_payment_block': False,
                'policy_line_id': False,
                'block_reason': False,
            })
            _logger.debug('[VPA_POLICY] no_policy bill_id=%s finding_id=%s', self.id, finding.id)
            return

        line = policy._get_matching_line(finding)
        if line:
            requires_block = line.action == 'block'
            block_reason = False
            if requires_block:
                block_reason = _('%(variance)s blocks payment: %(finding)s. Required procedure: %(procedure)s.') % {
                    'variance': finding.variance_type_id.name,
                    'finding': finding.name,
                    'procedure': dict(line._fields['resolution_requirement'].selection).get(line.resolution_requirement),
                }
            finding.write({
                'requires_payment_block': requires_block,
                'policy_line_id': line.id,
                'block_reason': block_reason,
            })
            _logger.info(
                '[VPA_POLICY] evaluated bill_id=%s finding_id=%s policy_id=%s line_id=%s action=%s block=%s',
                self.id,
                finding.id,
                policy.id,
                line.id,
                line.action,
                requires_block,
            )
            return

        default_block = policy.default_behavior == 'block'
        finding.write({
            'requires_payment_block': default_block,
            'policy_line_id': False,
            'block_reason': _('Payment blocked by default vendor audit policy: %s.') % finding.name if default_block else False,
        })
        _logger.info(
            '[VPA_POLICY] default bill_id=%s finding_id=%s policy_id=%s block=%s',
            self.id,
            finding.id,
            policy.id,
            default_block,
        )

    def _vendor_payment_audit_collect_findings(self):
        self.ensure_one()
        payloads = []
        for collector in self._vendor_payment_audit_get_collectors():
            payloads.extend(collector())
        _logger.debug('[VPA_SOURCE] collected bill_id=%s count=%s', self.id, len(payloads))
        return payloads

    def _vendor_payment_audit_get_collectors(self):
        self.ensure_one()
        return [
            self._vendor_payment_audit_collect_price_discrepancies,
            self._vendor_payment_audit_collect_promised_cost_differences,
            self._vendor_payment_audit_collect_invoice_variances,
            self._vendor_payment_audit_collect_promotion_commitments,
        ]

    def _vendor_payment_audit_collect_price_discrepancies(self):
        self.ensure_one()
        if 'vendor.price.discrepancy' not in self.env:
            return []
        payloads = []
        for discrepancy in self.env['vendor.price.discrepancy'].sudo().search([('bill_id', '=', self.id)]):
            variance_amount = discrepancy.price_difference_lowest or discrepancy.price_difference_average or 0.0
            variance_percent = discrepancy.percentage_diff_lowest or discrepancy.percentage_diff_average or 0.0
            payloads.append({
                'name': _('Price discrepancy for %s') % discrepancy.product_id.display_name,
                'variance_type_code': 'price_discrepancy',
                'severity': 'medium',
                'source_code': 'vendor_price_check',
                'source_model': discrepancy._name,
                'source_record_id': discrepancy.id,
                'source_key': 'vendor_price_check:%s' % discrepancy.id,
                'product_id': discrepancy.product_id.id,
                'expected_amount': discrepancy.lowest_price or discrepancy.average_price or 0.0,
                'actual_amount': discrepancy.vendor_price,
                'variance_amount': variance_amount,
                'variance_percent': variance_percent,
                'debug_payload': {
                    'lowest_price': discrepancy.lowest_price,
                    'average_price': discrepancy.average_price,
                    'bill_count': discrepancy.bill_count,
                },
            })
        return payloads

    def _vendor_payment_audit_collect_promised_cost_differences(self):
        self.ensure_one()
        payloads = []
        required_fields = {'vendor_promised_cost_vat_incl', 'promised_cost_difference_vat_incl'}
        if not required_fields.issubset(self.env['account.move.line']._fields):
            return payloads
        rounding = self.currency_id.rounding or 0.01
        for line in self.invoice_line_ids.filtered(
            lambda item: (
                item.display_type not in ('line_section', 'line_note')
                and item.vendor_promised_cost_vat_incl
                and abs(item.promised_cost_difference_vat_incl) > rounding
            )
        ):
            promised = line.vendor_promised_cost_vat_incl
            actual = promised + line.promised_cost_difference_vat_incl
            payloads.append({
                'name': _('Promised cost difference for %s') % (line.product_id.display_name or line.name),
                'variance_type_code': 'promised_cost_difference',
                'severity': 'high' if line.promised_cost_difference_vat_incl > 0 else 'medium',
                'source_code': 'purchase_net_price_compute',
                'source_model': line._name,
                'source_record_id': line.id,
                'source_key': 'promised_cost_difference:%s' % line.id,
                'product_id': line.product_id.id,
                'invoice_line_id': line.id,
                'expected_amount': promised,
                'actual_amount': actual,
                'variance_amount': line.promised_cost_difference_vat_incl,
                'variance_percent': (line.promised_cost_difference_vat_incl / promised * 100.0) if promised else 0.0,
                'debug_payload': {
                    'quantity': line.quantity,
                    'line_name': line.name,
                },
            })
        return payloads

    def _vendor_payment_audit_collect_invoice_variances(self):
        self.ensure_one()
        payloads = []
        if 'vendor.bill.invoice.variance.audit' not in self.env:
            return payloads
        audits = self.env['vendor.bill.invoice.variance.audit'].sudo().search([('bill_id', '=', self.id)])
        for audit in audits:
            severity = getattr(audit, 'severity', False) or 'high'
            state = getattr(audit, 'state', False)
            if state in ('resolved', 'approved', 'done', 'closed'):
                continue
            signed_variance = getattr(audit, 'variance_amount', 0.0) or getattr(audit, 'amount_difference', 0.0) or 0.0
            absolute_variance = getattr(audit, 'absolute_variance_amount', 0.0) or abs(signed_variance)
            calculated_total = getattr(audit, 'calculated_total_vat_incl', 0.0) or 0.0
            vendor_total = getattr(audit, 'vendor_invoice_final_total', 0.0) or 0.0
            allowed_variance = getattr(audit, 'allowed_variance_amount', 0.0) or 0.0
            payloads.append({
                'name': getattr(audit, 'display_name', False) or _('Invoice variance audit'),
                'variance_type_code': 'invoice_variance',
                'severity': severity if severity in ('low', 'medium', 'high', 'critical') else 'high',
                'source_code': 'invoice_variance_audit',
                'source_model': audit._name,
                'source_record_id': audit.id,
                'source_key': 'invoice_variance_audit:%s' % audit.id,
                'expected_amount': calculated_total,
                'actual_amount': vendor_total,
                'variance_amount': absolute_variance,
                'variance_percent': (absolute_variance / calculated_total * 100.0) if calculated_total else 0.0,
                'resolution_tolerance_amount': allowed_variance,
                'debug_payload': {
                    'state': state,
                    'signed_variance_amount': signed_variance,
                    'absolute_variance_amount': absolute_variance,
                    'allowed_variance_amount': allowed_variance,
                    'calculated_total_vat_incl': calculated_total,
                    'vendor_invoice_final_total': vendor_total,
                },
            })
        return payloads

    def _vendor_payment_audit_collect_promotion_commitments(self):
        self.ensure_one()
        if 'promotion_payment_hold' not in self._fields or not self.promotion_payment_hold:
            return []
        outstanding = getattr(self, 'promotion_outstanding_foc_qty', 0.0) or 0.0
        return [{
            'name': getattr(self, 'promotion_hold_reason', False) or _('Vendor promotion commitment is outstanding'),
            'variance_type_code': 'promotion_commitment',
            'severity': 'high',
            'source_code': 'vendor_purchase_promotions',
            'source_model': self._name,
            'source_record_id': self.id,
            'source_key': 'vendor_purchase_promotions:%s' % self.id,
            'variance_amount': outstanding,
            'debug_payload': {
                'promotion_release_state': getattr(self, 'promotion_release_state', False),
                'promotion_outstanding_foc_qty': outstanding,
            },
        }]

    def _vendor_payment_audit_check_allowed(self, operation='payment'):
        candidates = self.filtered(lambda move: move.move_type == 'in_invoice' and move.state == 'posted')
        if not candidates:
            return True
        candidates._vendor_payment_audit_scan()
        blocked = candidates.filtered('vendor_payment_audit_blocked')
        if blocked:
            _logger.warning(
                '[VPA_PAYMENT_GUARD] blocked operation=%s bill_ids=%s user_id=%s reasons=%s',
                operation,
                blocked.ids,
                self.env.user.id,
                blocked.mapped('vendor_payment_audit_block_reason'),
            )
            raise ValidationError(_(
                'Vendor payment is blocked for: %(bills)s\n\n%(reasons)s'
            ) % {
                'bills': ', '.join(blocked.mapped('display_name')),
                'reasons': '\n'.join(filter(None, blocked.mapped('vendor_payment_audit_block_reason'))),
            })
        _logger.debug(
            '[VPA_PAYMENT_GUARD] allowed operation=%s bill_ids=%s user_id=%s',
            operation,
            candidates.ids,
            self.env.user.id,
        )
        return True

    def action_vendor_payment_audit_scan(self):
        self._vendor_payment_audit_scan()
        return True

    def action_view_vendor_payment_audit_case(self):
        self.ensure_one()
        case = self._vendor_payment_audit_get_or_create_case()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Payment Audit'),
            'res_model': 'vendor.payment.audit.case',
            'res_id': case.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_post(self):
        result = super().action_post()
        self.filtered(lambda move: move.move_type == 'in_invoice')._vendor_payment_audit_scan()
        self.filtered(lambda move: move.move_type == 'in_refund').mapped('reversed_entry_id').filtered(
            lambda move: move.move_type == 'in_invoice'
        )._vendor_payment_audit_scan()
        return result

    def action_register_payment(self):
        self._vendor_payment_audit_check_allowed(operation='register_payment')
        return super().action_register_payment()

    def action_force_register_payment(self):
        self._vendor_payment_audit_check_allowed(operation='force_register_payment')
        return super().action_force_register_payment()

    def js_assign_outstanding_line(self, line_id):
        self._vendor_payment_audit_check_allowed(operation='assign_outstanding_line')
        return super().js_assign_outstanding_line(line_id)

    def action_toggle_block_payment(self):
        for move in self:
            if move.vendor_payment_audit_blocked:
                raise ValidationError(_('This bill is blocked by Vendor Payment Auditing. Resolve or waive the audit findings first.'))
        return super().action_toggle_block_payment()
