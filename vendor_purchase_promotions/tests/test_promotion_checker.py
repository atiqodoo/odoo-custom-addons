from odoo import fields
from odoo.tests.common import TransactionCase

from ..services.promotion_opportunity import calculate_next_promotion_tier


class TestPromotionOpportunityCalculator(TransactionCase):

    def test_buy_nine_quantity_fifteen_recommends_three_more(self):
        result = calculate_next_promotion_tier(
            charged_qty=15,
            buy_qty=9,
            free_qty=1,
            min_charged_qty=1,
            repeat_offer=True,
        )
        self.assertEqual(result['current_foc_qty'], 1)
        self.assertEqual(result['quantity_to_add'], 3)
        self.assertEqual(result['recommended_qty'], 18)
        self.assertEqual(result['recommended_foc_qty'], 2)

    def test_exact_repeat_tier_has_no_opportunity(self):
        self.assertIsNone(calculate_next_promotion_tier(
            charged_qty=18,
            buy_qty=9,
            free_qty=1,
            min_charged_qty=1,
            repeat_offer=True,
        ))

    def test_non_repeating_offer_stops_after_first_reward(self):
        self.assertIsNone(calculate_next_promotion_tier(
            charged_qty=15,
            buy_qty=9,
            free_qty=1,
            min_charged_qty=1,
            repeat_offer=False,
        ))


class TestPromotionCheckerOverride(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Promotion Checker Vendor',
            'supplier_rank': 1,
        })
        cls.product = cls.env['product.product'].search([
            ('purchase_ok', '=', True),
            ('active', '=', True),
            ('is_storable', '=', True),
        ], limit=1)
        cls.assertTrue(cls.product, 'A purchasable stock product is required')
        cls.promotion = cls.env['vendor.purchase.promotion'].create({
            'name': 'Checker Buy 9 Get 1',
            'company_id': cls.env.company.id,
            'partner_id': cls.vendor.id,
            'calculation_profile': 'generic',
            'product_tmpl_ids': [(6, 0, [cls.product.product_tmpl_id.id])],
            'min_charged_qty': 1,
            'buy_qty': 9,
            'free_qty': 1,
            'repeat_offer': True,
            'priority': 999,
        })

    def _create_order(self, qty=15):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'vendor_promised_cost_contact': 'Promotion Checker Test',
        })
        line = self.env['purchase.order.line'].with_context(
            skip_rfq_bill_price=True
        ).create({
            'order_id': order.id,
            'product_id': self.product.id,
            'name': self.product.display_name,
            'product_qty': qty,
            'product_uom': self.product.uom_po_id.id,
            'price_unit': 100,
            'date_planned': fields.Datetime.now(),
        })
        return order, line

    def test_two_banner_dismissals_allow_audited_override(self):
        order, line = self._create_order(15)

        first_action = order.button_confirm()
        self.assertEqual(
            first_action['tag'],
            'vendor_purchase_promotions.promotion_warning',
        )
        log = order.promotion_override_log_ids
        self.assertEqual(len(log), 1)
        self.assertEqual(log.dismissal_count, 0)
        self.assertEqual(log.line_ids.quantity_to_add, 3)
        self.assertEqual(log.line_ids.recommended_qty, 18)
        log.action_register_dismissal(first_action['params']['fingerprint'])
        self.assertEqual(log.dismissal_count, 1)

        second_action = order.button_confirm()
        self.assertEqual(
            second_action['tag'],
            'vendor_purchase_promotions.promotion_warning',
        )
        log.action_register_dismissal(second_action['params']['fingerprint'])
        self.assertEqual(log.dismissal_count, 2)
        self.assertTrue(log.override_available)

        order.button_confirm()
        self.assertNotIn(order.state, ('draft', 'sent'))
        self.assertTrue(log.override_used)
        self.assertTrue(log.override_confirmed_at)
        self.assertEqual(line.promotion_foc_qty, 1)
        self.assertEqual(line.promotion_foc_line_ids.product_qty, 1)
        self.assertIn('override_confirmed', log.event_ids.mapped('event_type'))

    def test_quantity_change_starts_a_new_dismissal_cycle(self):
        order, line = self._create_order(15)
        action = order.button_confirm()
        first_log = order.promotion_override_log_ids
        first_log.action_register_dismissal(action['params']['fingerprint'])
        self.assertEqual(first_log.dismissal_count, 1)

        line.product_qty = 16
        changed_action = order.button_confirm()
        changed_log = order.promotion_override_log_ids.sorted('id')[-1]
        self.assertNotEqual(changed_log.id, first_log.id)
        self.assertNotEqual(changed_log.fingerprint, first_log.fingerprint)
        self.assertEqual(changed_log.dismissal_count, 0)
        self.assertEqual(changed_action['params']['log_id'], changed_log.id)

    def test_exact_promotion_tier_confirms_without_warning_log(self):
        order, line = self._create_order(18)
        order.button_confirm()
        self.assertNotIn(order.state, ('draft', 'sent'))
        self.assertFalse(order.promotion_override_log_ids)
        self.assertEqual(line.promotion_foc_qty, 2)

