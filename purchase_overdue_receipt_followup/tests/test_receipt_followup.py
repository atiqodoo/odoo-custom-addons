from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


# Monday 2 Nov 2026, 10:00 Nairobi / 07:00 UTC.
NOW = datetime(2026, 11, 2, 7)


@tagged('post_install', '-at_install')
class TestReceiptFollowup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'receipt_followup_enabled': True,
            'receipt_followup_calendar_id': cls.env.ref('purchase_overdue_receipt_followup.receiving_calendar').id})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.vendor = cls.env['res.partner'].create({'name': 'Receipt Test Vendor', 'supplier_rank': 1})
        cls.product = cls.env['product.product'].create({'name': 'Receipt Test Variant', 'is_storable': True, 'available_in_pos': True,
            'purchase_ok': True, 'route_ids': [Command.set(cls.warehouse.buy_pull_id.route_id.ids)]})
        cls.seller = cls.env['product.supplierinfo'].create({'partner_id': cls.vendor.id,
            'product_tmpl_id': cls.product.product_tmpl_id.id, 'product_id': cls.product.id, 'price': 100})
        cls.reference_type = cls.env['purchase.vendor.reference.type'].create({'name': 'Receipt Test Ref'})
        cls.po = cls.env['purchase.order'].create({'partner_id': cls.vendor.id,
            'company_id': cls.company.id, 'picking_type_id': cls.warehouse.in_type_id.id,
            'vendor_reference_type_id': cls.reference_type.id, 'partner_ref': 'FOLLOWUP-ORIGINAL'})
        cls.line = cls.env['purchase.order.line'].create({'order_id': cls.po.id,
            'product_id': cls.product.id, 'product_qty': 20, 'product_uom': cls.product.uom_id.id})
        cls.po.write({'state': 'purchase'})
        cls.op = cls.env['stock.warehouse.orderpoint'].create({'product_id': cls.product.id,
            'company_id': cls.company.id, 'warehouse_id': cls.warehouse.id,
            'location_id': cls.warehouse.lot_stock_id.id, 'product_min_qty': 4, 'product_max_qty': 16,
            'route_id': cls.warehouse.buy_pull_id.route_id.id, 'trigger': 'auto'})
        cls.move = cls.env['stock.move'].create({'name': 'Late supplier receipt', 'product_id': cls.product.id,
            'product_uom': cls.product.uom_id.id, 'product_uom_qty': 20,
            'company_id': cls.company.id, 'location_id': cls.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': cls.warehouse.lot_stock_id.id, 'purchase_line_id': cls.line.id,
            'date': datetime(2026, 10, 30, 12), 'state': 'confirmed'})
        cls.env['stock.quant']._update_available_quantity(cls.product, cls.warehouse.lot_stock_id, -4)
        cls.alert_model = cls.env['purchase.receipt.followup']

    def _scan(self, now=NOW):
        self.alert_model._scan_orderpoints(self.op, now=now)
        return self.alert_model.search([('orderpoint_id', '=', self.op.id)])

    def _replacement(self, alert):
        action = alert.action_review()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        wizard.write({'quantity': 20, 'reason': 'Vendor cannot confirm delivery; replacement approved.',
            'expected_date': NOW + timedelta(days=1),
            'vendor_reference_type_id': self.reference_type.id, 'vendor_reference': 'FOLLOWUP-REPLACEMENT'})
        return wizard

    def test_review_button_action_preparation(self):
        from odoo.addons.web.controllers.utils import clean_action

        buyer = new_test_user(self.env, login='followup_review_buyer', groups='purchase.group_purchase_user')
        alert = self._scan().with_user(buyer)
        action = clean_action(alert.action_review(), env=alert.env)
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['views'], [(False, 'form')])
        wizard = alert.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.followup_id, alert)
        self.assertFalse(alert.replacement_order_id, 'Review alone must not request replacement supply')

    def test_calendar_boundaries_and_weekend_deadline(self):
        policy = self.env['purchase.receiving.calendar']
        friday = datetime(2026, 10, 30, 12)
        for closed in [datetime(2026, 10, 31, 10), datetime(2026, 11, 1, 7), datetime(2026, 11, 2, 4, 59)]:
            self.assertFalse(policy._is_overdue(self.company, friday, closed))
        self.assertTrue(policy._is_overdue(self.company, friday, datetime(2026, 10, 31, 9, 59)))
        sunday_due = datetime(2026, 11, 1, 7)
        self.assertFalse(policy._is_overdue(self.company, sunday_due, datetime(2026, 11, 2, 5)))
        self.assertTrue(policy._is_overdue(self.company, sunday_due, datetime(2026, 11, 2, 5, 1)))
        self.assertFalse(policy._is_open(self.company, datetime(2026, 11, 2, 14)))

    def test_working_grace_and_holiday(self):
        self.company.receipt_followup_grace_hours = 2
        policy = self.env['purchase.receiving.calendar']
        self.assertFalse(policy._is_overdue(self.company, datetime(2026, 11, 2, 5), NOW))
        self.assertTrue(policy._is_overdue(self.company, datetime(2026, 11, 2, 5), NOW + timedelta(minutes=1)))
        self.env['resource.calendar.leaves'].create({'name': 'Receiving holiday',
            'calendar_id': self.company.receipt_followup_calendar_id.id,
            'date_from': datetime(2026, 11, 2), 'date_to': datetime(2026, 11, 3)})
        self.assertFalse(policy._is_open(self.company, NOW))

    def test_settings_enable_and_calendar_save_together(self):
        calendar = self.company.receipt_followup_calendar_id
        self.company.write({'receipt_followup_enabled': False, 'receipt_followup_calendar_id': False})
        settings = self.env['res.config.settings'].create({
            'company_id': self.company.id, 'receipt_followup_enabled': True,
            'receipt_followup_calendar_id': calendar.id, 'receipt_followup_grace_hours': 3,
        })
        self.assertFalse(self.company.receipt_followup_enabled)
        self.assertFalse(self.company.receipt_followup_calendar_id)
        settings.set_values()
        self.assertTrue(self.company.receipt_followup_enabled)
        self.assertEqual(self.company.receipt_followup_calendar_id, calendar)
        self.assertEqual(self.company.receipt_followup_grace_hours, 3)

    def test_settings_invalid_calendar_still_rejected(self):
        self.company.write({'receipt_followup_enabled': False, 'receipt_followup_calendar_id': False})
        settings = self.env['res.config.settings'].create({
            'company_id': self.company.id, 'receipt_followup_enabled': True,
            'receipt_followup_calendar_id': False,
        })
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            settings.set_values()
        self.assertFalse(self.company.receipt_followup_enabled)

    def test_settings_load_company_values_without_writing_other_company(self):
        settings = self.env['res.config.settings'].create({'company_id': self.company.id})
        self.assertTrue(settings.receipt_followup_enabled)
        self.assertEqual(settings.receipt_followup_calendar_id, self.company.receipt_followup_calendar_id)
        other = self.env['res.company'].create({'name': 'Settings Other Receiving Company'})
        other.write({'receipt_followup_enabled': False, 'receipt_followup_grace_hours': 1})
        settings.company_id = other
        self.assertFalse(settings.receipt_followup_enabled)
        self.assertEqual(settings.receipt_followup_grace_hours, 1)
        self.assertTrue(self.company.receipt_followup_enabled)

    def test_settings_reject_negative_grace_and_unauthorized_save(self):
        settings = self.env['res.config.settings'].create({'company_id': self.company.id,
                                                          'receipt_followup_grace_hours': -1})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            settings.set_values()
        buyer = new_test_user(self.env, login='receiving_settings_buyer', groups='purchase.group_purchase_user')
        with self.assertRaises(AccessError):
            settings.with_user(buyer).set_values()

    def test_scan_is_idempotent_and_does_not_change_forecast(self):
        before = self.product.virtual_available
        alert = self._scan()
        self.assertEqual(alert.overdue_qty, 20)
        self.assertEqual(alert.suggested_qty, 20)
        self.assertEqual(alert.reliable_forecast_qty, -4)
        self.assertEqual(self._scan(), alert)
        self.assertEqual(self.product.virtual_available, before)

    def test_future_or_cancelled_receipts_resolve(self):
        alert = self._scan()
        self.move.date = NOW + timedelta(days=1)
        self._scan()
        self.assertEqual(alert.state, 'resolved')
        self.move.write({'date': NOW - timedelta(days=1), 'state': 'cancel'})
        self._scan()
        self.assertEqual(alert.state, 'resolved')

    def test_closed_hours_and_manual_rules_do_not_warn(self):
        self.assertFalse(self._scan(datetime(2026, 11, 1, 7)))
        self.op.trigger = 'manual'
        self.assertFalse(self._scan())

    def test_other_draft_supply_prevents_duplicate(self):
        draft = self.env['purchase.order'].create({'partner_id': self.vendor.id,
            'picking_type_id': self.warehouse.in_type_id.id,
            'vendor_reference_type_id': self.reference_type.id, 'partner_ref': 'FOLLOWUP-OTHER'})
        self.env['purchase.order.line'].create({'order_id': draft.id, 'product_id': self.product.id,
            'product_qty': 20, 'product_uom': self.product.uom_id.id, 'orderpoint_id': self.op.id})
        self.assertEqual(self._scan().suggested_qty, 0)

    def test_partial_receipt_counts_only_remaining_backorder(self):
        self.move.quantity = 8
        self.move.picked = True
        self.move._action_done()
        alert = self._scan()
        self.assertEqual(alert.overdue_qty, 12)
        self.assertNotIn(self.move, alert.move_ids)

    def test_multistep_receipt_counts_supplier_leg_once(self):
        input_location = self.env['stock.location'].create({'name': 'Receiving Input',
            'usage': 'internal', 'company_id': self.company.id})
        self.move.write({'location_dest_id': input_location.id,
                         'location_final_id': self.warehouse.lot_stock_id.id})
        self.env['stock.move'].create({'name': 'Internal receiving leg', 'product_id': self.product.id,
            'product_uom': self.product.uom_id.id, 'product_uom_qty': 20,
            'company_id': self.company.id, 'location_id': input_location.id,
            'location_dest_id': self.warehouse.lot_stock_id.id, 'purchase_line_id': self.line.id,
            'date': self.move.date, 'state': 'waiting'})
        self.assertEqual(self._scan().overdue_qty, 20)

    def test_add_to_existing_draft_and_buyer_authorization(self):
        draft = self.env['purchase.order'].create({'partner_id': self.vendor.id,
            'picking_type_id': self.warehouse.in_type_id.id,
            'vendor_reference_type_id': self.reference_type.id, 'partner_ref': 'FOLLOWUP-EXISTING'})
        buyer = new_test_user(self.env, login='followup_authorized_buyer', groups='purchase.group_purchase_user')
        alert = self._scan().with_user(buyer)
        action = alert.action_review()
        wizard = self.env[action['res_model']].with_user(buyer).browse(action['res_id'])
        wizard.write({'target_order_id': draft.id, 'quantity': 20,
            'reason': 'Supplier confirmed shipment is unavailable.', 'expected_date': NOW + timedelta(days=1)})
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            action = wizard.action_create_rfq()
        self.assertEqual(action['res_id'], draft.id)
        self.assertEqual(draft.order_line.product_id, self.product)
        self.assertEqual(alert.replacement_user_id, buyer)

    def test_replacement_and_repeat_click(self):
        alert = self._scan()
        wizard = self._replacement(alert)
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            action = wizard.action_create_rfq()
            order = self.env['purchase.order'].browse(action['res_id'])
            self.assertEqual(order.state, 'draft')
            self.assertEqual(order.order_line.product_id, self.product)
            self.assertEqual(order.order_line.product_qty, 20)
            self.assertEqual(alert.replacement_order_id, order)
            with self.assertRaises(UserError):
                wizard.action_create_rfq()
        self.assertEqual(self.move.state, 'confirmed')
        self.assertEqual(self._scan().state, 'replaced')

    def test_replacement_requires_reason_and_fresh_quantity(self):
        wizard = self._replacement(self._scan())
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            wizard.reason = ''
            with self.assertRaises(ValidationError):
                wizard.action_create_rfq()
            wizard.reason = 'Followed up with vendor'
            self.env['stock.quant']._update_available_quantity(self.product, self.warehouse.lot_stock_id, 30)
            with self.assertRaises(UserError):
                wizard.action_create_rfq()

    def test_purchase_user_cannot_forge_alert(self):
        buyer = new_test_user(self.env, login='followup_buyer', groups='purchase.group_purchase_user')
        alert = self._scan().with_user(buyer)
        with self.assertRaises(AccessError):
            alert.write({'suggested_qty': 1000})
        internal = new_test_user(self.env, login='followup_internal', groups='base.group_user')
        self.assertFalse(self.alert_model.with_user(internal).get_popup_warning())
        with self.assertRaises(AccessError):
            alert.with_user(internal).action_review()

    def test_company_boundary_and_popup_working_hours(self):
        alert = self._scan()
        with patch.object(fields.Datetime, 'now', return_value=datetime(2026, 11, 1, 7)):
            self.assertFalse(self.alert_model.get_popup_warning())
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            self.assertEqual(self.alert_model.get_popup_warning()['id'], alert.id)
        other = self.env['res.company'].create({'name': 'Other Receiving Company'})
        buyer = new_test_user(self.env, login='followup_other_buyer', groups='purchase.group_purchase_user',
                              company_id=other.id, company_ids=[Command.set(other.ids)])
        with self.assertRaises(AccessError):
            alert.with_user(buyer).with_context(allowed_company_ids=other.ids).action_review()

    def test_manual_or_archived_rule_suppresses_existing_popup(self):
        self._scan()
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            self.op.trigger = 'manual'
            self.assertFalse(self.alert_model.get_popup_warning())
            self.op.write({'trigger': 'auto', 'active': False})
            self.assertFalse(self.alert_model.get_popup_warning())

    def test_purchase_user_can_create_new_replacement_with_reference(self):
        buyer = new_test_user(self.env, login='followup_new_rfq_buyer', groups='purchase.group_purchase_user')
        alert = self._scan().with_user(buyer)
        action = alert.action_review()
        wizard = self.env[action['res_model']].with_user(buyer).browse(action['res_id'])
        wizard.write({'quantity': 20, 'reason': 'Supplier confirmed stock is unavailable.',
            'expected_date': NOW + timedelta(days=1), 'vendor_reference_type_id': self.reference_type.id,
            'vendor_reference': 'FOLLOWUP-BUYER-NEW'})
        with patch.object(fields.Datetime, 'now', return_value=NOW):
            action = wizard.action_create_rfq()
        order = self.env['purchase.order'].browse(action['res_id'])
        self.assertEqual(order.partner_ref, 'FOLLOWUP-BUYER-NEW')
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.create_uid, buyer)

    def test_backend_warning_asset_compiles(self):
        bundle = self.env['ir.qweb']._get_asset_bundle('web.assets_backend', css=False, js=True)
        attachment = bundle.js()
        self.assertTrue(attachment)
        self.assertIn(b'purchase_overdue_receipt_followup', attachment.raw)
