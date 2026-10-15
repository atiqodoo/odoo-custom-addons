from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.addons.stock_account.tests.test_anglo_saxon_valuation_reconciliation_common import ValuationReconciliationTestCommon


@tagged('-at_install', 'post_install')
class TestPostedBillCosting(ValuationReconciliationTestCommon):
    @classmethod
    def default_env_context(cls):
        # Valid fixtures also when paint_colour_master requires POS availability.
        return {**super().default_env_context(), 'default_available_in_pos': True,
                'default_available_on_pos': True}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.anglo_saxon_accounting = True
        cls.category = cls.stock_account_product_categ.copy({
            'name': 'POS posted bill test', 'property_cost_method': 'average',
            'property_stock_journal': cls.company_data['default_journal_misc'].id,
            'property_account_creditor_price_difference_categ': cls.company_data['default_account_expense'].id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'POS posted bill product', 'is_storable': True,
            'categ_id': cls.category.id, 'standard_price': 100,
            'purchase_method': 'purchase', 'supplier_taxes_id': False, 'taxes_id': False,
        })
        cls.supplier = cls.env['res.partner'].create({'name': 'POS costing vendor'})
        cls.Allocation = cls.env['pos.neg.receipt.allocation']
        cls.Settlement = cls.env['pos.neg.bill.settlement']

    def _sell(self, quantity=1, lot=None):
        warehouse = self.company_data['default_warehouse']
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
        })
        move = self.env['stock.move'].create({
            'name': 'POS oversell', 'picking_id': picking.id,
            'product_id': self.product.id, 'product_uom': self.product.uom_id.id,
            'product_uom_qty': quantity, 'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })
        move._action_confirm()
        move.quantity = quantity
        if lot:
            move.move_line_ids.lot_id = lot
        move.picked = True
        picking.with_context(pos_allow_negative_stock=True)._action_done()
        layer = move.stock_valuation_layer_ids.filtered(lambda l: l.quantity < 0)
        layer.write({'pos_negative_origin': True})
        self.assertTrue(layer.pos_neg_bill_costing)
        return layer

    def _purchase(self, quantity=1, price=120):
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'name': self.product.name,
                                   'product_qty': quantity, 'product_uom': self.product.uom_id.id,
                                   'price_unit': price, 'date_planned': fields.Datetime.now(),
                                   'taxes_id': False})],
        })
        po.button_confirm()
        return po

    def _receive(self, po, quantity=None, lot=None):
        picking = po.picking_ids.filtered(lambda p: p.state != 'done')
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty if quantity is None else quantity
            if lot:
                move.move_line_ids.lot_id = lot
            move.picked = True
        picking.with_context(pos_allow_negative_stock=True)._action_done()
        return picking.move_ids

    def _bill(self, po, quantity=1, price=125, discount=0, post=True):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice', 'partner_id': self.supplier.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id, 'product_uom_id': self.product.uom_id.id,
                'quantity': quantity, 'price_unit': price, 'discount': discount,
                'purchase_line_id': po.order_line.id, 'tax_ids': False,
                'account_id': self.company_data['default_account_stock_in'].id,
            })],
        })
        if post:
            bill.action_post()
        return bill

    def _assert_finalized(self, quantity, difference):
        settlements = self.Settlement.search([('allocation_id.product_id', '=', self.product.id)])
        self.assertAlmostEqual(sum(settlements.mapped('quantity')), quantity)
        entries = settlements.price_diff_move_id
        lines = entries.line_ids.filtered(lambda l: l.account_id == self.category._get_price_diff_account())
        self.assertAlmostEqual(sum(lines.mapped('balance')), difference, places=2)
        self.assertTrue(all(entry.state == 'posted' for entry in entries))
        self.assertFalse(self.Allocation.search([('product_id', '=', self.product.id)]).filtered('error_message'))

    def test_receipt_waits_for_posted_bill_and_balances_stock(self):
        layer = self._sell()
        po = self._purchase()
        self._receive(po)
        self.assertFalse(self.Settlement.search([]))
        self.assertEqual(layer.reconciled_qty, 0)
        self.assertAlmostEqual(self.product.value_svl, 20)
        bill = self._bill(po, post=False)
        self.Allocation.search([])._settle_available()
        self.assertFalse(self.Settlement.search([]))
        bill.action_post()
        self._assert_finalized(1, 25)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)
        self.assertAlmostEqual(sum(self.env['account.move.line'].search([
            ('product_id', '=', self.product.id), ('account_id', '=', self.category.property_stock_valuation_account_id.id),
            ('move_id.state', '=', 'posted')]).mapped('balance')), 0, places=2)

    def test_bill_before_receipt(self):
        self._sell()
        po = self._purchase()
        self._bill(po)
        self.assertFalse(self.Settlement.search([]))
        self._receive(po)
        self._assert_finalized(1, 25)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_bill_before_receipt_with_received_quantity_invoice_policy(self):
        self.product.purchase_method = 'receive'
        self._sell()
        po = self._purchase()
        self._bill(po)
        self._receive(po)
        self._assert_finalized(1, 25)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)
        self.assertAlmostEqual(sum(self.env['account.move.line'].search([
            ('product_id', '=', self.product.id), ('account_id', '=', self.category.property_stock_valuation_account_id.id),
            ('move_id.state', '=', 'posted')]).mapped('balance')), 0, places=2)

    def test_partial_bills_do_not_reuse_quantities(self):
        layer = self._sell(3)
        po = self._purchase(3)
        self._receive(po)
        self._bill(po, 1, 125)
        self._assert_finalized(1, 25)
        self.assertEqual(layer.reconciled_qty, 1)
        self._bill(po, 2, 130)
        self._assert_finalized(3, 85)
        self.Allocation.search([])._settle_available()
        self._assert_finalized(3, 85)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_multiple_receipts_and_normal_units(self):
        self._sell(2)
        po = self._purchase(3)
        self._receive(po)
        self._bill(po, 3, 125)
        self._assert_finalized(2, 50)
        self.assertAlmostEqual(self.product.value_svl, 125, places=2)
        self.assertAlmostEqual(self.product.standard_price, 125, places=2)

    def test_discount_uses_posted_amount(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        self._bill(po, price=150, discount=20)
        self._assert_finalized(1, 20)

    def test_zero_cost_bill_is_valid(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        self._bill(po, price=0)
        self._assert_finalized(1, -100)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_equal_cost_has_audit_without_journal(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        self._bill(po, price=100)
        self._assert_finalized(1, 0)
        self.assertFalse(self.Settlement.search([]).price_diff_move_id)

    def test_posting_failure_can_retry_without_losing_quantity(self):
        layer = self._sell()
        po = self._purchase()
        self._receive(po)
        bill = self._bill(po, post=False)
        original = type(self.env['account.move'])._post

        def fail_settlement(records, soft=True):
            if records.filtered('pos_neg_settlement_entry'):
                raise UserError('Test journal failure')
            return original(records, soft=soft)

        with patch.object(type(bill), '_post', fail_settlement):
            bill.action_post()
        self.assertFalse(self.Settlement.search([]))
        self.assertEqual(layer.reconciled_qty, 0)
        allocation = self.Allocation.search([])
        self.assertTrue(allocation.error_message)
        allocation.action_retry()
        self._assert_finalized(1, 25)

    def test_missing_configuration_leaves_pending(self):
        layer = self._sell()
        po = self._purchase()
        self._receive(po)
        self.category.property_account_creditor_price_difference_categ = False
        self._bill(po)
        self.assertFalse(self.Settlement.search([]))
        self.assertEqual(layer.reconciled_qty, 0)
        self.assertTrue(self.Allocation.search([]).error_message)

    def test_reserved_quantity_cannot_be_reused_by_adjustment(self):
        layer = self._sell()
        po = self._purchase()
        self._receive(po)
        self.assertEqual(layer._pos_neg_unreserved_quantity(), 0)

    def test_inventory_gain_keeps_standard_valuation_correction(self):
        layer = self._sell()
        self.product.with_context(disable_auto_svl=True).standard_price = 200
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product.id), ('location_id.usage', '=', 'internal')])
        quant.with_context(inventory_mode=True).inventory_quantity = 0
        quant.with_context(pos_allow_negative_stock=True)._apply_inventory()
        self.assertFalse(self.Settlement.search([]))
        self.assertTrue(layer.is_fully_reconciled)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_inventory_user_cannot_retry_financial_posting(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        with self.assertRaises(AccessError):
            self.Allocation.search([]).with_user(self.res_users_stock_user).action_retry()

    def test_corrections_require_explicit_review(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        bill = self._bill(po)
        with self.assertRaises(UserError):
            bill.button_draft()
        with self.assertRaises(UserError):
            self.Settlement.search([]).price_diff_move_id._reverse_moves()
        refund = bill._reverse_moves()[0]
        with self.assertRaises(UserError):
            refund.action_post()

    def test_legacy_layers_are_not_reposted(self):
        layer = self._sell()
        layer.pos_neg_bill_costing = False
        po = self._purchase()
        self._receive(po)
        self._bill(po)
        self.assertFalse(self.Settlement.search([]))

    def test_company_rule(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        allocation = self.Allocation.search([])
        other = self.setup_other_company(name='POS bill isolation')['company']
        user = self.res_users_stock_user
        user.company_ids |= other
        restricted = allocation.with_user(user).with_context(allowed_company_ids=[other.id])
        with self.assertRaises(AccessError):
            restricted.check_access('read')

    def test_separate_receipts_keep_their_bill_costs(self):
        self._sell(3)
        first = self._purchase(1, 120)
        second = self._purchase(2, 130)
        self._receive(first)
        self._receive(second)
        self._bill(second, 2, 140)
        self._assert_finalized(2, 80)
        self._bill(first, 1, 125)
        self._assert_finalized(3, 105)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_bill_cannot_finalize_unreceived_units(self):
        self._sell(3)
        po = self._purchase(3)
        self._receive(po, quantity=1)
        self._bill(po, quantity=3)
        self._assert_finalized(1, 25)
        self._receive(po)
        self._assert_finalized(3, 75)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_only_shortfall_is_owned(self):
        opening = self._purchase(2, 100)
        self._receive(opening)
        self._bill(opening, 2, 100)
        layer = self._sell(3)
        self.assertEqual(layer.pos_neg_exposure_qty, 1)
        po = self._purchase()
        self._receive(po)
        self._bill(po)
        self._assert_finalized(1, 25)
        self.assertTrue(layer.is_fully_reconciled)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_older_non_pos_shortage_owns_first_receipt(self):
        non_pos = self._sell()
        non_pos.write({'pos_neg_bill_costing': False, 'pos_negative_origin': False})
        layer = self._sell()
        first = self._purchase()
        self._receive(first)
        self.assertFalse(self.Allocation.search([]))
        self.assertEqual(layer.remaining_qty, -1)
        second = self._purchase()
        self._receive(second)
        self._bill(second)
        self._assert_finalized(1, 25)

    def test_bill_uom_conversion(self):
        self._sell(12)
        po = self._purchase(12)
        self._receive(po)
        bill = self._bill(po, post=False)
        bill.invoice_line_ids.write({'product_uom_id': self.env.ref('uom.product_uom_dozen').id,
                                     'quantity': 1, 'price_unit': 1500})
        bill.action_post()
        self._assert_finalized(12, 300)
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_foreign_bill_uses_posted_exchange_rate(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        foreign = self.env.ref('base.EUR')
        if foreign == self.env.company.currency_id:
            foreign = self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.env.company.id,
                                              'name': fields.Date.today(), 'rate': 2})
        bill = self._bill(po, price=250, post=False)
        bill.currency_id = foreign
        bill.action_post()
        posted_cost = bill.invoice_line_ids.balance / bill.invoice_line_ids.quantity
        self._assert_finalized(1, self.env.company.currency_id.round(posted_cost - 100))
        self.assertAlmostEqual(self.product.value_svl, 0, places=2)

    def test_accountant_can_finalize_without_inventory_write_access(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        bill = self._bill(po, post=False)
        from odoo.tests.common import new_test_user
        accountant = new_test_user(self.env, login='pos_bill_accountant',
                                   groups='account.group_account_user,purchase.group_purchase_user')
        bill.with_user(accountant).action_post()
        self._assert_finalized(1, 25)

    def test_users_cannot_edit_allocation_bookkeeping(self):
        self._sell()
        po = self._purchase()
        self._receive(po)
        with self.assertRaises(AccessError):
            self.Allocation.search([]).with_user(self.res_users_stock_user).write({'quantity': 99})

    def test_lot_receipt_cannot_cover_another_lot(self):
        self.product.write({'tracking': 'lot', 'lot_valuated': True})
        lots = self.env['stock.lot'].create([
            {'name': 'NEG-A', 'product_id': self.product.id, 'standard_price': 100},
            {'name': 'NORMAL-B', 'product_id': self.product.id, 'standard_price': 100},
        ])
        layer = self._sell(lot=lots[0])
        unrelated = self._purchase()
        self._receive(unrelated, lot=lots[1])
        self.assertFalse(self.Allocation.search([]))
        self.assertEqual(layer.remaining_qty, -1)
        replenishment = self._purchase()
        self._receive(replenishment, lot=lots[0])
        self._bill(replenishment)
        self._assert_finalized(1, 25)
        self.assertAlmostEqual(lots[0].value_svl, 0, places=2)
        self.assertAlmostEqual(lots[1].value_svl, 120, places=2)

    def test_partial_bills_respect_lot_offsets_in_one_receipt(self):
        self.product.write({'tracking': 'lot', 'lot_valuated': True})
        negative, ordinary = self.env['stock.lot'].create([
            {'name': 'NEG-A', 'product_id': self.product.id, 'standard_price': 100},
            {'name': 'NORMAL-B', 'product_id': self.product.id, 'standard_price': 100},
        ])
        self._sell(lot=negative)
        po = self._purchase(2)
        picking = po.picking_ids
        move = picking.move_ids
        move.move_line_ids.unlink()
        for lot in (ordinary, negative):
            self.env['stock.move.line'].create({
                'move_id': move.id, 'product_id': self.product.id,
                'product_uom_id': self.product.uom_id.id,
                'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id,
                'lot_id': lot.id, 'quantity': 1,
            })
        move.picked = True
        picking.with_context(pos_allow_negative_stock=True)._action_done()
        allocation = self.Allocation.search([])
        self.assertEqual(allocation.receipt_offset, 1)
        self._bill(po, quantity=1)
        self.assertFalse(self.Settlement.search([]))
        self._bill(po, quantity=1, price=130)
        self._assert_finalized(1, 30)
        self.assertAlmostEqual(negative.value_svl, 0, places=2)
        self.assertAlmostEqual(ordinary.value_svl, 125, places=2)
