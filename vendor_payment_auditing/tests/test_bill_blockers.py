from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, ValidationError


class TestBillBlockerDisplay(TransactionCase):

    def test_only_active_blockers_are_listed_and_update_independently(self):
        vendor = self.env['res.partner'].create({'name': 'Audit blocker test vendor'})
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': vendor.id})
        case = self.env['vendor.payment.audit.case'].create({'bill_id': bill.id})
        variance_type = self.env.ref('vendor_payment_auditing.variance_type_invoice_variance')
        findings = self.env['vendor.payment.audit.finding'].create([
            {'case_id': case.id, 'name': 'First blocker', 'variance_type_id': variance_type.id,
             'source_code': 'test', 'source_key': 'test:first', 'requires_payment_block': True},
            {'case_id': case.id, 'name': 'Second blocker', 'variance_type_id': variance_type.id,
             'source_code': 'test', 'source_key': 'test:second', 'requires_payment_block': True},
            {'case_id': case.id, 'name': 'Review only', 'variance_type_id': variance_type.id,
             'source_code': 'test', 'source_key': 'test:review', 'requires_payment_block': False},
        ])
        self.assertEqual(set(bill.vendor_payment_audit_blocking_finding_ids.ids), set(findings[:2].ids))
        findings[0].write({'state': 'resolved', 'requires_payment_block': False})
        self.assertEqual(bill.vendor_payment_audit_blocking_finding_ids, findings[1])
        self.assertTrue(bill.vendor_payment_audit_blocked)
        findings[1].write({'state': 'resolved', 'requires_payment_block': False})
        self.assertFalse(bill.vendor_payment_audit_blocking_finding_ids)
        self.assertFalse(bill.vendor_payment_audit_blocked)

    def test_waiver_requires_type_and_reason_and_affects_one_finding(self):
        self.env.user.write({'groups_id': [(4, self.env.ref('vendor_payment_auditing.group_vendor_payment_audit_manager').id)]})
        vendor = self.env['res.partner'].create({'name': 'Waiver test vendor'})
        bill = self.env['account.move'].create({'move_type': 'in_invoice', 'partner_id': vendor.id})
        case = self.env['vendor.payment.audit.case'].create({'bill_id': bill.id})
        variance_type = self.env.ref('vendor_payment_auditing.variance_type_invoice_variance')
        findings = self.env['vendor.payment.audit.finding'].create([
            {'case_id': case.id, 'name': 'Variance', 'variance_type_id': variance_type.id,
             'source_code': 'test', 'source_key': 'test:waiver1', 'requires_payment_block': True},
            {'case_id': case.id, 'name': 'Other', 'variance_type_id': variance_type.id,
             'source_code': 'test', 'source_key': 'test:waiver2', 'requires_payment_block': True},
        ])
        self.assertEqual(case.action_approve_waiver()['res_model'], 'vendor.payment.audit.waiver.wizard')
        with self.assertRaises(ValidationError):
            findings[0]._approve_waiver('invoice_variance', '  ')
        with self.assertRaises(AccessError):
            findings[0].write({'state': 'waived'})
        wizard = self.env['vendor.payment.audit.waiver.wizard'].create({
            'case_id': case.id, 'finding_id': findings[0].id,
            'waiver_type': 'invoice_variance', 'reason': 'Supplier confirmed adjustment',
        })
        wizard.action_confirm()
        self.assertEqual(findings[0].state, 'waived')
        self.assertEqual(findings[0].waiver_type, 'invoice_variance')
        self.assertEqual(findings[0].waiver_reason, 'Supplier confirmed adjustment')
        self.assertEqual(findings[1].state, 'open')
        self.assertTrue(bill.vendor_payment_audit_blocked)
