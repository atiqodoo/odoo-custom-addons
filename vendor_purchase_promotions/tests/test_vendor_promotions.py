from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestVendorPromotions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Gamma Test Vendor',
            'supplier_rank': 1,
            'vendor_invoice_profile': 'gamma_paints',
        })
        # This database has a legacy NOT NULL product column no longer backed
        # by an installed field.  Reuse an existing purchasable stock product
        # so the promotion test remains independent of that unrelated schema.
        cls.product = cls.env['product.product'].search([
            ('purchase_ok', '=', True),
            ('active', '=', True),
            ('is_storable', '=', True),
        ], limit=1)
        cls.assertTrue(cls.product, 'A purchasable stock product is required')
        cls.promotion = cls.env['vendor.purchase.promotion'].create({
            'name': 'Gamma Buy 22 Get 2',
            'company_id': cls.env.company.id,
            'partner_id': cls.vendor.id,
            'calculation_profile': 'gamma_paints',
            'product_tmpl_ids': [(6, 0, [cls.product.product_tmpl_id.id])],
            'min_charged_qty': 22,
            'buy_qty': 22,
            'free_qty': 2,
            'repeat_offer': True,
            'override_discount': True,
            'discount_percentage': 40,
            'default_tint_type': 'factory',
            'default_tint_percentage': 7,
        })

    def _create_order(self, qty=22):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'vendor_promised_cost_contact': 'Gamma Sales',
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
            'gamma_list_unit_price': 100,
            'gamma_discount_percentage': 40,
            'gamma_tint_type': 'factory',
            'gamma_tint_percentage': 7,
        })
        return order, line

    def test_repeating_foc_calculation(self):
        self.assertEqual(self.promotion.calculate_foc_qty(21), 0)
        self.assertEqual(self.promotion.calculate_foc_qty(22), 2)
        self.assertEqual(self.promotion.calculate_foc_qty(43), 2)
        self.assertEqual(self.promotion.calculate_foc_qty(44), 4)

    def test_rule_supports_several_products(self):
        templates = self.env['product.template'].search([
            ('purchase_ok', '=', True),
            ('active', '=', True),
            ('id', '!=', self.product.product_tmpl_id.id),
        ], limit=1)
        self.assertTrue(templates, 'A second purchasable product is required')
        self.promotion.product_tmpl_ids = [(4, templates.id)]
        self.assertIn(templates, self.promotion.product_tmpl_ids)

    def test_sync_creates_separate_zero_cost_foc_line(self):
        order, line = self._create_order()
        order._sync_vendor_promotions()
        foc_line = line.promotion_foc_line_ids
        self.assertEqual(len(foc_line), 1)
        self.assertEqual(line.product_qty, 22)
        self.assertEqual(line.promotion_foc_qty, 2)
        self.assertEqual(foc_line.product_qty, 2)
        self.assertEqual(foc_line.price_unit, 0)
        self.assertFalse(foc_line.taxes_id)
        self.assertTrue(foc_line.is_promotion_foc)
        self.assertAlmostEqual(line.price_unit, 67.0)

    def test_application_tracks_outstanding_foc(self):
        order, line = self._create_order()
        order._sync_vendor_promotions()
        order._create_promotion_applications()
        application = order.promotion_application_ids
        self.assertEqual(len(application), 1)
        self.assertEqual(application.charged_qty, 22)
        self.assertEqual(application.promised_foc_qty, 2)
        self.assertEqual(application.received_foc_qty, 0)
        self.assertEqual(application.outstanding_foc_qty, 2)
        self.assertEqual(application.fulfillment_state, 'awaiting')

    def test_grouped_gamma_tiers_select_highest_slab(self):
        second_product = self.env['product.product'].search([
            ('purchase_ok', '=', True),
            ('active', '=', True),
            ('is_storable', '=', True),
            ('id', '!=', self.product.id),
        ], limit=1)
        self.assertTrue(second_product, 'A second purchasable stock product is required')
        deal_key = 'gamma_test_slab'
        self.promotion.write({
            'deal_group_key': deal_key,
            'product_tmpl_ids': [(4, second_product.product_tmpl_id.id)],
            'min_charged_qty': 22,
            'buy_qty': 22,
            'free_qty': 2,
        })
        second_tier = self.env['vendor.purchase.promotion'].create({
            'name': 'Gamma Buy 48 Get 5',
            'company_id': self.env.company.id,
            'partner_id': self.vendor.id,
            'calculation_profile': 'gamma_paints',
            'deal_group_key': deal_key,
            'product_tmpl_ids': [(6, 0, [
                self.product.product_tmpl_id.id,
                second_product.product_tmpl_id.id,
            ])],
            'min_charged_qty': 48,
            'buy_qty': 48,
            'free_qty': 5,
            'repeat_offer': True,
        })
        order, first_line = self._create_order(qty=24)
        second_line = self.env['purchase.order.line'].with_context(
            skip_rfq_bill_price=True
        ).create({
            'order_id': order.id,
            'product_id': second_product.id,
            'name': second_product.display_name,
            'product_qty': 24,
            'product_uom': second_product.uom_po_id.id,
            'price_unit': 100,
            'date_planned': fields.Datetime.now(),
            'gamma_list_unit_price': 100,
        })

        order._sync_vendor_promotions()

        foc_lines = order.order_line.filtered('is_promotion_foc')
        self.assertEqual(len(foc_lines), 1)
        self.assertEqual(foc_lines.promotion_id, second_tier)
        self.assertEqual(foc_lines.product_qty, 5)
        self.assertEqual(set(foc_lines.promotion_qualifying_line_ids.ids), set((first_line | second_line).ids))

    def test_outstanding_foc_blocks_bill_payment_until_waiver(self):
        order, _line = self._create_order()
        order._sync_vendor_promotions()
        order._create_promotion_applications()
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'promotion_application_ids': [(6, 0, order.promotion_application_ids.ids)],
            'promotion_release_state': 'hold',
        })
        self.assertTrue(bill.promotion_payment_hold)
        bill._sync_promotion_payment_hold()
        self.assertEqual(bill.payment_state, 'blocked')
        with self.assertRaises(ValidationError):
            bill.action_register_payment()

        bill.promotion_release_reason = 'Manager-approved supplier delay'
        bill.action_waive_promotion_hold()
        self.assertFalse(bill.promotion_payment_hold)
        self.assertEqual(bill.promotion_release_state, 'waived')

    def test_fulfilled_foc_is_automatically_released(self):
        order, _line = self._create_order()
        order._sync_vendor_promotions()
        order._create_promotion_applications()
        application = order.promotion_application_ids
        # Model the completed receipt state without creating a stock transfer.
        application.promised_foc_qty = 0
        application._compute_foc_status()
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'promotion_application_ids': [(6, 0, application.ids)],
            'promotion_release_state': 'hold',
        })
        bill._sync_promotion_payment_hold()
        self.assertFalse(bill.promotion_payment_hold)
        self.assertEqual(bill.promotion_release_state, 'released')
        self.assertNotEqual(bill.payment_state, 'blocked')
