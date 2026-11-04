from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestPurchaseStockCompare(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.category = cls.env['product.category'].create({'name': 'Compare Trade'})
        cls.attribute = cls.env['product.attribute'].create({'name': 'Compare Colour'})
        cls.white = cls.env['product.attribute.value'].create({'name': 'Brilliant White', 'attribute_id': cls.attribute.id})
        cls.black = cls.env['product.attribute.value'].create({'name': 'Black', 'attribute_id': cls.attribute.id})
        cls.products = cls.env['product.product']
        for name, value in [('Original Covermat', cls.white), ('Similar Trade', cls.white), ('Different Colour', cls.black)]:
            template = cls.env['product.template'].create({
                'name': name, 'is_storable': True, 'purchase_ok': True, 'categ_id': cls.category.id,
                'attribute_line_ids': [Command.create({'attribute_id': cls.attribute.id, 'value_ids': [Command.set(value.ids)]})],
            })
            cls.products |= template.product_variant_id
        cls.original, cls.similar, cls.different = cls.products
        cls.op = cls.env['stock.warehouse.orderpoint'].create({
            'product_id': cls.original.id, 'location_id': cls.warehouse.lot_stock_id.id,
            'warehouse_id': cls.warehouse.id, 'company_id': cls.company.id})
        cls.vendor = cls.env['res.partner'].create({'name': 'Compare Vendor', 'supplier_rank': 1})
        cls.colour = cls.env['colour.code'].create({
            'code': 'COMPARE-WHITE', 'name': 'Brilliant White', 'vendor_id': cls.vendor.id,
            'fandeck_id': cls.env['colour.fandeck'].create({'name': 'Comparison Test Deck'}).id})
        cls.group = cls.env['modern.quotation.colour.attribute.group'].create({
            'name': 'Comparison White Equivalence', 'colour_code_ids': [Command.set(cls.colour.ids)],
            'attribute_value_ids': [Command.set(cls.white.ids)]})

    def _wizard(self):
        action = self.env['purchase.variant.stock.compare']._open_for_orderpoint(self.op)
        return self.env[action['res_model']].browse(action['res_id'])

    def _plain_product(self, name, **values):
        return self.env['product.product'].create(dict({
            'name': name, 'is_storable': True, 'purchase_ok': True,
            'available_in_pos': True, 'categ_id': self.category.id,
        }, **values))

    def test_no_colour_data_falls_back_to_category_and_exact_uom(self):
        source = self._plain_product('Uncoloured Turpentine')
        alternative = self._plain_product('Alternative Turpentine')
        self.op.product_id = source
        other_category = self.env['product.category'].create({'name': 'Outside Turpentine'})
        outside = self._plain_product('Unrelated Category', categ_id=other_category.id)
        other_uom = self.env['uom.uom'].create({'name': 'Fallback Other Pack',
            'category_id': source.uom_id.category_id.id, 'uom_type': 'bigger', 'factor_inv': 4})
        wrong_pack = self._plain_product('Wrong Pack', uom_id=other_uom.id, uom_po_id=other_uom.id)
        wizard = self._wizard()
        self.assertIn(alternative, wizard.line_ids.product_id)
        self.assertNotIn(outside, wizard.line_ids.product_id)
        self.assertNotIn(wrong_pack, wizard.line_ids.product_id)
        self.assertIn('Category/UoM fallback', wizard.match_description)

    def test_no_matching_colour_alternative_uses_fallback(self):
        self.similar.active = False
        wizard = self._wizard()
        self.assertIn(self.different, wizard.line_ids.product_id)
        self.assertIn('Category/UoM fallback', wizard.match_description)
        self.assertNotIn(self.similar, wizard.line_ids.product_id)

    def test_matching_zero_stock_alternative_prevents_fallback(self):
        wizard = self._wizard()
        self.assertIn(self.similar, wizard.line_ids.product_id)
        self.assertEqual(wizard.line_ids.filtered(lambda row: row.product_id == self.similar).on_hand, 0)
        self.assertNotIn(self.different, wizard.line_ids.product_id)
        self.assertNotIn('Category/UoM fallback', wizard.match_description)

    def test_no_exact_colour_code_alternative_uses_fallback(self):
        self.group.active = False
        source = self._plain_product('Standalone Colour Code White', colour_code_id=self.colour.id)
        self.op.product_id = source
        wizard = self._wizard()
        self.assertIn(self.similar, wizard.line_ids.product_id)
        self.assertIn('Category/UoM fallback', wizard.match_description)

    def test_fallback_group_scope_is_opt_in(self):
        source = self._plain_product('Uncoloured Category Source')
        self.op.product_id = source
        sibling = self.env['product.category'].create({'name': 'Fallback Group Sibling'})
        alternative = self._plain_product('Other Group Product', categ_id=sibling.id)
        self.env['modern.quotation.category.group'].create({'name': 'Fallback Combined Categories',
            'child_category_ids': [Command.set((self.category | sibling).ids)]})
        wizard = self._wizard()
        self.assertFalse(wizard.use_category_group)
        self.assertNotIn(alternative, wizard.line_ids.product_id)
        wizard.use_category_group = True
        wizard.action_refresh()
        self.assertIn(alternative, wizard.line_ids.product_id)
        self.assertIn('Category/UoM fallback', wizard.match_description)

    def test_fallback_preserves_eligibility_company_and_limit(self):
        source = self._plain_product('ZZZ Fallback Source')
        self.op.product_id = source
        company = self.env['res.company'].create({'name': 'Fallback Other Company'})
        foreign = self._plain_product('Foreign Product', company_id=company.id)
        not_purchasable = self._plain_product('Not Purchasable', purchase_ok=False)
        buyer = new_test_user(self.env, login='fallback_buyer', groups='purchase.group_purchase_user')
        action = self.env['purchase.variant.stock.compare'].with_user(buyer)._open_for_orderpoint(self.op)
        wizard = self.env[action['res_model']].with_user(buyer).browse(action['res_id'])
        self.assertNotIn(foreign, wizard.line_ids.product_id)
        self.assertNotIn(not_purchasable, wizard.line_ids.product_id)
        self.env['ir.config_parameter'].sudo().set_param('purchase_variant_stock_compare.result_limit', 1)
        wizard.action_refresh()
        self.assertTrue(wizard.truncated)
        self.assertIn(source, wizard.line_ids.product_id)
        self.assertLessEqual(len(wizard.line_ids), 2)

    def test_mapping_and_live_quantities(self):
        self.env['stock.quant']._update_available_quantity(self.original, self.warehouse.lot_stock_id, -4)
        self.env['stock.quant']._update_available_quantity(self.similar, self.warehouse.lot_stock_id, 9)
        self.env['stock.quant']._update_reserved_quantity(self.similar, self.warehouse.lot_stock_id, 2)
        wizard = self._wizard()
        self.assertEqual(wizard.colour_group_id, self.group)
        self.assertEqual(wizard.line_ids.product_id, self.original | self.similar)
        row = wizard.line_ids.filtered(lambda item: item.product_id == self.similar)
        self.assertEqual((row.on_hand, row.reserved, row.free_qty), (9, 2, 7))
        self.assertEqual(wizard.line_ids.filtered('is_original').on_hand, -4)

    def test_no_mapping_keeps_exact_attributes(self):
        self.group.active = False
        wizard = self._wizard()
        self.assertFalse(wizard.colour_group_id)
        self.assertIn(self.similar, wizard.line_ids.product_id)
        self.assertNotIn(self.different, wizard.line_ids.product_id)

    def test_colour_code_products_share_group(self):
        product = self.env['product.product'].create({
            'name': 'Colour Master White', 'is_storable': True, 'purchase_ok': True, 'available_in_pos': True,
            'categ_id': self.category.id, 'colour_code_id': self.colour.id})
        self.assertIn(product, self._wizard().line_ids.product_id)

    def test_purchase_only_product_is_included(self):
        self.similar.sale_ok = False
        self.assertIn(self.similar, self._wizard().line_ids.product_id)

    def test_category_defaults_do_not_broaden_to_siblings(self):
        parent = self.env['product.category'].create({'name': 'Comparison Parent'})
        sibling = self.env['product.category'].create({'name': 'Other Trade', 'parent_id': parent.id})
        self.category.parent_id = parent
        self.similar.categ_id = sibling
        self.assertNotIn(self.similar, self._wizard().line_ids.product_id)
        category_group = self.env['modern.quotation.category.group'].create({'name': 'Comparison Combined Trade',
            'child_category_ids': [Command.set((self.category | sibling).ids)]})
        wizard = self._wizard()
        self.assertEqual(wizard.category_group_id, category_group)
        self.assertFalse(wizard.use_category_group)
        self.assertEqual(wizard.category_id, self.original.categ_id)
        self.assertNotIn(self.similar, wizard.line_ids.product_id)
        wizard.use_category_group = True
        wizard.action_refresh()
        self.assertIn(self.similar, wizard.line_ids.product_id)
        self.assertNotIn(self.different, wizard.line_ids.product_id)
        wizard.use_category_group = False
        wizard.action_refresh()
        self.assertNotIn(self.similar, wizard.line_ids.product_id)

    def test_group_mode_requires_an_active_group(self):
        wizard = self._wizard()
        wizard.write({'use_category_group': True, 'category_group_id': False})
        with self.assertRaises(UserError):
            wizard.action_refresh()
        category_group = self.env['modern.quotation.category.group'].create({
            'name': 'Archived Comparison Category Group',
            'child_category_ids': [Command.set(self.category.ids)], 'active': False})
        wizard.category_group_id = category_group
        with self.assertRaises(UserError):
            wizard.action_refresh()
        wizard.use_category_group = False
        wizard.action_refresh()
        self.assertTrue(wizard.line_ids)

    def test_rfq_line_action_preserves_order(self):
        reference_type = self.env['purchase.vendor.reference.type'].create({'name': 'Comparison RFQ Ref'})
        order = self.env['purchase.order'].create({'partner_id': self.vendor.id,
            'picking_type_id': self.warehouse.in_type_id.id,
            'vendor_reference_type_id': reference_type.id, 'partner_ref': 'COMPARE-RFQ'})
        line = self.env['purchase.order.line'].create({'order_id': order.id, 'product_id': self.original.id,
            'product_qty': 3, 'product_uom': self.original.uom_id.id})
        before = (line.product_id, line.product_qty, line.price_unit, order.state)
        action = line.action_compare_similar_stock()
        wizard = self.env[action['res_model']].browse(action['res_id'])
        self.assertEqual(wizard.order_line_id, line)
        self.assertEqual((line.product_id, line.product_qty, line.price_unit, order.state), before)

    def test_exact_uom_and_result_limit(self):
        other_uom = self.env['uom.uom'].create({'name': 'Compare Other Pack',
            'category_id': self.original.uom_id.category_id.id, 'uom_type': 'bigger', 'factor_inv': 4})
        self.similar.write({'uom_id': other_uom.id, 'uom_po_id': other_uom.id})
        self.assertNotIn(self.similar, self._wizard().line_ids.product_id)

    def test_stock_scope_excludes_other_location(self):
        other = self.env['stock.location'].create({'name': 'Unrelated Internal', 'usage': 'internal',
                                                 'company_id': self.company.id})
        self.env['stock.quant']._update_available_quantity(self.similar, other, 100)
        row = self._wizard().line_ids.filtered(lambda item: item.product_id == self.similar)
        self.assertEqual(row.on_hand, 0)

    def test_purchase_user_and_company_boundary(self):
        buyer = new_test_user(self.env, login='compare_buyer', groups='purchase.group_purchase_user')
        action = self.env['purchase.variant.stock.compare'].with_user(buyer)._open_for_orderpoint(self.op)
        wizard = self.env[action['res_model']].with_user(buyer).browse(action['res_id'])
        self.assertTrue(wizard.line_ids)
        other = self.env['res.company'].create({'name': 'Compare Other Company'})
        with self.assertRaises(AccessError):
            wizard.with_context(allowed_company_ids=other.ids).action_refresh()

    def test_non_purchase_user_cannot_compare(self):
        internal = new_test_user(self.env, login='compare_internal', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.env['purchase.variant.stock.compare'].with_user(internal)._open_for_orderpoint(self.op)
