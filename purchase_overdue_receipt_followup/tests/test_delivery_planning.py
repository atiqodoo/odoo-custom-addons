from datetime import datetime
from unittest.mock import patch
from uuid import uuid4
from pathlib import Path

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file


MONDAY = datetime(2026, 11, 2, 7)  # 10:00 Nairobi


@tagged('post_install', '-at_install')
class TestVendorDeliveryPlanning(TransactionCase):
    def test_developer_xml_view_loader(self):
        # Valid XML alone does not exercise dev=xml's direct source-file loader.
        root = Path(__file__).resolve().parents[1]
        for path in root.rglob('*.xml'):
            tree = etree.parse(str(path))
            for record in tree.xpath("//record[@model='ir.ui.view'][field[@name='arch']]"):
                xmlid = 'purchase_overdue_receipt_followup.' + record.get('id')
                with self.subTest(view=xmlid):
                    arch = get_view_arch_from_file(str(path), xmlid)
                    self.assertIsNotNone(etree.fromstring(arch))

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.env.ref('purchase_overdue_receipt_followup.receiving_calendar')
        cls.company.write({'receipt_followup_calendar_id': cls.calendar.id,
                           'delivery_hours_per_day': 9, 'po_lock': 'edit'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Calendar Delivery Vendor', 'supplier_rank': 1})
        cls.product = cls.env['product.product'].create({'name': 'Delivery Schedule Test',
            'available_in_pos': True, 'is_storable': True, 'purchase_ok': True})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.ref_type = cls.env['purchase.vendor.reference.type'].create({'name': 'Delivery Planning Ref'})
        cls.planner = cls.env['purchase.delivery.planning']
        cls.policy = cls.env['purchase.vendor.delivery.policy'].create({
            'partner_id': cls.vendor.id, 'company_id': cls.company.id, 'days': 1, 'hours': 3})

    def _order(self, **values):
        order = self.env['purchase.order'].create(dict({
            'partner_id': self.vendor.id, 'company_id': self.company.id,
            'picking_type_id': self.warehouse.in_type_id.id,
            'vendor_reference_type_id': self.ref_type.id, 'partner_ref': 'DELIVERY-' + uuid4().hex,
        }, **values))
        self.env['purchase.order.line'].create({'order_id': order.id, 'product_id': self.product.id,
            'product_qty': 20, 'product_uom': self.product.uom_id.id, 'price_unit': 10})
        return order

    def _calculate(self, start, days=1, hours=3, **options):
        return self.planner._calculate(self.company, self.calendar, start, days, hours, 9, **options)

    def _confirm(self, order, at=MONDAY):
        with patch.object(fields.Datetime, 'now', return_value=at):
            order.button_confirm()
        self.assertEqual(order.state, 'purchase')

    def test_mixed_days_hours_and_half_day(self):
        self.assertEqual(self._calculate(MONDAY), datetime(2026, 11, 3, 10))
        self.assertEqual(self._calculate(datetime(2026, 11, 6, 7)), datetime(2026, 11, 7, 10))
        self.assertEqual(self._calculate(datetime(2026, 11, 6, 12)), datetime(2026, 11, 9, 10))
        self.assertEqual(self._calculate(datetime(2026, 11, 6, 13), 0, 1.5), datetime(2026, 11, 7, 5, 30))

    def test_sunday_holiday_and_zero_duration(self):
        self.assertEqual(self._calculate(datetime(2026, 11, 1, 7), 0, 0), datetime(2026, 11, 2, 5))
        self.env['resource.calendar.leaves'].create({'name': 'Delivery holiday', 'calendar_id': self.calendar.id,
            'date_from': datetime(2026, 11, 2), 'date_to': datetime(2026, 11, 3)})
        self.assertEqual(self._calculate(MONDAY), datetime(2026, 11, 4, 8))

    def test_preferred_time_never_shortens_duration(self):
        self.assertEqual(self._calculate(MONDAY, preferred=True, preferred_time=15), datetime(2026, 11, 3, 12))
        self.assertEqual(self._calculate(datetime(2026, 11, 6, 7), preferred=True, preferred_time=15),
                         datetime(2026, 11, 9, 12))
        with self.assertRaises(ValidationError):
            self._calculate(MONDAY, preferred=True, preferred_time=3)

    def test_vendor_defaults_preview_and_actual_approval(self):
        order = self._order(delivery_preview_start=datetime(2026, 11, 1, 7))
        self.assertEqual((order.delivery_days, order.delivery_hours, order.delivery_day_hours), (1, 3, 9))
        self.assertEqual(order.delivery_total_hours, 12)
        order.action_preview_delivery()
        self.assertFalse(order.delivery_original_arrival)
        self._confirm(order)
        self.assertEqual(order.delivery_start_at, order.date_approve)
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 3, 10))
        self.assertEqual(order.delivery_original_arrival, order.delivery_current_arrival)
        self.assertEqual(order.order_line.move_ids.date, order.delivery_current_arrival)

    def test_draft_arrival_automatic_and_not_reset_by_quantity(self):
        self.policy.write({'days': 2, 'hours': 2, 'use_preferred_time': True, 'preferred_time': 15})
        order = self._order(delivery_preview_start=datetime(2026, 11, 2, 3, 5, 49))
        expected = datetime(2026, 11, 4, 12)  # Wednesday 15:00 Nairobi
        self.assertEqual(order.date_planned, expected)
        self.assertEqual(order.order_line.date_planned, expected)
        self.assertFalse(order.delivery_original_arrival)
        order.order_line.product_qty = 30
        self.assertEqual(order.order_line.date_planned, expected)
        self.assertEqual(order.date_planned, expected)

    def test_draft_override_recalculates_without_preview_button(self):
        order = self._order(delivery_preview_start=MONDAY)
        order.write({'delivery_mode': 'duration', 'delivery_days': 0, 'delivery_hours': 2})
        self.assertEqual(order.date_planned, datetime(2026, 11, 2, 9))
        self.assertFalse(order.delivery_original_arrival)

    def test_unsaved_draft_onchange_uses_vendor_calendar(self):
        order = self.env['purchase.order'].new({'partner_id': self.vendor.id,
            'company_id': self.company.id, 'delivery_mode': 'vendor', 'delivery_preview_start': MONDAY})
        order._onchange_delivery_vendor()
        order._onchange_draft_delivery_arrival()
        self.assertEqual(order.date_planned, datetime(2026, 11, 3, 10))
        self.assertFalse(order.delivery_original_arrival)

    def test_fixed_draft_arrival_survives_quantity_repricing(self):
        expected = datetime(2026, 11, 3, 12)
        order = self._order(delivery_mode='fixed', delivery_fixed_arrival=expected)
        order.order_line.product_qty = 35
        self.assertEqual(order.date_planned, expected)

    def test_header_onchange_keeps_manual_line_promise(self):
        order = self._order(delivery_preview_start=MONDAY)
        expected = datetime(2026, 11, 4, 12)
        order.order_line.write({'delivery_manual_arrival': True, 'delivery_fixed_arrival': expected})
        order.date_planned = datetime(2026, 11, 3, 10)
        order.onchange_date_planned()
        self.assertEqual(order.order_line.date_planned, expected)

    def test_duration_override_does_not_change_vendor_policy(self):
        order = self._order(delivery_mode='duration', delivery_days=0, delivery_hours=2)
        self._confirm(order)
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 2, 9))
        self.assertEqual((self.policy.days, self.policy.hours), (1, 3))

    def test_fixed_arrival_and_line_override_survive_confirmation(self):
        order = self._order(delivery_mode='fixed', delivery_fixed_arrival=datetime(2026, 11, 3, 12))
        order.order_line.write({'delivery_manual_arrival': True,
                               'delivery_fixed_arrival': datetime(2026, 11, 3, 13)})
        self._confirm(order)
        self.assertEqual(order.order_line.date_planned, datetime(2026, 11, 3, 13))
        self.assertEqual(order.order_line.move_ids.date, datetime(2026, 11, 3, 13))
        self.assertEqual(order.delivery_original_arrival, datetime(2026, 11, 3, 13))

    def test_fixed_closed_time_or_before_confirmation_rejected(self):
        order = self._order(delivery_mode='fixed', delivery_fixed_arrival=datetime(2026, 11, 8, 7))
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._confirm(order)
        order.delivery_fixed_arrival = datetime(2026, 11, 2, 6)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._confirm(order)

    def test_approval_request_does_not_freeze_promise(self):
        order = self._order()
        order.state = 'to approve'
        self.assertFalse(order.delivery_original_arrival)
        with patch.object(fields.Datetime, 'now', return_value=MONDAY):
            order.button_approve()
        self.assertEqual(order.delivery_start_at, MONDAY)

    def test_no_vendor_policy_keeps_standard_dates(self):
        self.policy.active = False
        order = self._order()
        before = order.order_line.date_planned
        order._apply_delivery_plan(MONDAY)
        self.assertEqual(order.order_line.date_planned, before)
        self.assertFalse(order.delivery_snapshot)

    def test_standard_confirmation_captures_original_without_rescheduling(self):
        self.policy.active = False
        order = self._order()
        before = order.order_line.date_planned
        self._confirm(order)
        self.assertEqual(order.order_line.date_planned, before)
        self.assertEqual(order.delivery_original_arrival, before)
        self.assertEqual(order.delivery_snapshot['mode'], 'standard')

    def test_manual_line_without_vendor_policy_is_preserved(self):
        self.policy.active = False
        order = self._order()
        expected = datetime(2026, 11, 3, 12)
        order.order_line.write({'delivery_manual_arrival': True, 'delivery_fixed_arrival': expected})
        self._confirm(order)
        self.assertEqual(order.order_line.move_ids.date, expected)

    def test_duration_recalculate_and_policy_restore(self):
        order = self._order(delivery_mode='duration', delivery_days=0, delivery_hours=2,
                            delivery_preview_start=MONDAY)
        order.action_preview_delivery()
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 2, 9))
        order.action_restore_vendor_delivery()
        self.assertEqual(order.delivery_mode, 'vendor')
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 3, 10))

    def test_restore_without_policy_returns_to_standard_odoo(self):
        self.policy.active = False
        order = self._order(delivery_mode='duration', delivery_days=0, delivery_hours=2,
                            delivery_preview_start=MONDAY)
        expected = order.date_order
        order.action_preview_delivery()
        order.action_restore_vendor_delivery()
        self.assertEqual(order.order_line.date_planned, expected)
        self.assertFalse(order.delivery_snapshot)

    def test_direct_reschedule_needs_reason_and_original_is_frozen(self):
        order = self._order()
        self._confirm(order)
        before = order.delivery_original_arrival
        with self.assertRaises(ValidationError):
            order.write({'delivery_hours': 4})
        order.write({'delivery_mode': 'duration', 'delivery_days': 0, 'delivery_hours': 1,
                     'delivery_change_reason': 'Revised with supplier'})
        self.assertEqual(order.delivery_original_arrival, before)
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 2, 8))

    def test_managed_native_dates_cannot_bypass_revision_reason(self):
        order = self._order()
        self._confirm(order)
        with self.assertRaises(UserError):
            order.date_planned = datetime(2026, 11, 4, 12)
        with self.assertRaises(UserError):
            order.order_line.date_planned = datetime(2026, 11, 4, 12)

    def test_unmanaged_standard_date_edit_remains_available(self):
        self.policy.active = False
        order = self._order()
        self._confirm(order)
        order.order_line.date_planned = datetime(2026, 11, 4, 12)
        self.assertEqual(order.order_line.date_planned, datetime(2026, 11, 4, 12))

    def test_reschedule_as_purchase_user_and_wrong_line_rejected(self):
        order = self._order()
        other_order = self._order()
        self._confirm(order)
        buyer = new_test_user(self.env, login='delivery_reschedule_buyer', groups='purchase.group_purchase_user')
        action = order.with_user(buyer).action_reschedule_delivery()
        wizard = self.env[action['res_model']].with_user(buyer).browse(action['res_id'])
        wizard.write({'arrival_mode': 'fixed', 'fixed_arrival': datetime(2026, 11, 4, 12), 'reason': 'Vendor revised arrival'})
        wizard.line_ids.order_line_id = other_order.order_line
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            wizard.action_apply()
        wizard.line_ids.order_line_id = order.order_line
        wizard.action_apply()
        self.assertEqual(order.delivery_revision_user_id, buyer)

    def test_lookahead_is_bounded(self):
        self.company.delivery_planning_horizon_days = 1
        with self.assertRaises(ValidationError):
            self._calculate(MONDAY, 10, 0)

    def test_policy_changes_do_not_rewrite_confirmed_order(self):
        order = self._order()
        self._confirm(order)
        before = order.delivery_current_arrival
        self.policy.write({'days': 3, 'hours': 0})
        self.assertEqual(order.delivery_current_arrival, before)
        self.assertEqual(order.delivery_snapshot['days'], 1)
        with self.assertRaises(AccessError):
            order.write({'delivery_original_arrival': datetime(2026, 11, 5, 7)})

    def test_reschedule_updates_only_outstanding_receipts_and_keeps_original(self):
        order = self._order()
        self._confirm(order)
        move = order.order_line.move_ids
        move.quantity = 8
        move.picked = True
        move._action_done()
        completed_date = move.date
        original = order.delivery_original_arrival
        action = order.action_reschedule_delivery()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.write({'arrival_mode': 'fixed', 'fixed_arrival': datetime(2026, 11, 4, 12),
                      'reason': 'Supplier agreed a revised delivery.'})
        self.assertEqual(order.delivery_current_arrival, original)
        wizard.action_apply()
        self.assertEqual(move.date, completed_date)
        pending = order.order_line.move_ids.filtered(lambda item: item.state not in ('done', 'cancel'))
        self.assertEqual(pending.date, datetime(2026, 11, 4, 12))
        self.assertEqual(order.delivery_original_arrival, original)
        self.assertEqual(order.delivery_current_arrival, datetime(2026, 11, 4, 12))

    def test_policy_security_and_company_isolation(self):
        buyer = new_test_user(self.env, login='delivery_policy_buyer', groups='purchase.group_purchase_user')
        with self.assertRaises(AccessError):
            self.policy.with_user(buyer).write({'hours': 99})
        other = self.env['res.company'].create({'name': 'Delivery Other Company'})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.policy.copy({'company_id': other.id, 'calendar_id': self.calendar.copy({'company_id': self.company.id}).id})
        self.assertEqual(self.policy.with_user(buyer).company_id, self.company)

    def test_invalid_duration_and_day_conversion_rejected(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.policy.hours = -1
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.company.delivery_hours_per_day = 0
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._order(delivery_mode='duration', delivery_hours=-1)
