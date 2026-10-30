from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPendingSourceLinks(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.groups_id |= cls.env.ref('paint_pos_pending_collection.group_pending_collection_manager')
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.warehouse.int_type_id.active = True
        cls.config = cls.env['pos.config'].create({
            'name': 'Source link POS', 'picking_type_id': cls.warehouse.out_type_id.id,
        })
        cls.session = cls.env['pos.session'].create({'config_id': cls.config.id})
        cls.order = cls.env['pos.order'].create({
            'session_id': cls.session.id, 'company_id': cls.env.company.id,
            'amount_tax': 0, 'amount_total': 0, 'amount_paid': 0, 'amount_return': 0,
            'pos_reference': 'Source receipt',
        })
        cls.holding = cls.env['stock.location'].create({
            'name': 'Source holding', 'usage': 'internal',
            'location_id': cls.warehouse.lot_stock_id.id, 'company_id': cls.env.company.id,
        })
        cls.product = cls.env['product.product'].create({'name': 'Source pending product', 'is_storable': True})
        cls.worker = new_test_user(cls.env, login='source_pending_worker', groups='stock.group_stock_user')

    def _pending(self, **extra):
        return self.env['paint.pending.collection'].create({
            'pos_order_id': self.order.id, 'holding_location_id': self.holding.id,
            'collection_line_ids': [(0, 0, {'product_id': self.product.id,
                                         'product_uom_qty': 2, 'pending_qty': 2})],
            **extra,
        })

    def _picking(self, **extra):
        return self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.int_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.holding.id, **extra,
        })

    def _assert_sources(self, picking, pending):
        links = {(s['model'], s['id']) for s in picking.source_link_data}
        self.assertIn(('paint.pending.collection', pending.id), links)
        self.assertIn(('pos.order', self.order.id), links)
        self.assertFalse(picking.pos_order_id, 'Navigation must not modify native POS membership')

    def test_native_pos_delivery(self):
        picking = self._picking(pos_order_id=self.order.id)
        self.assertIn(('pos.order', self.order.id),
                      {(s['model'], s['id']) for s in picking.source_link_data})
        action = picking.action_open_source_link('pos.order', self.order.id)
        self.assertEqual(action['res_model'], 'pos.order')

    def test_workflow_holding_collection_and_cancel(self):
        self.env['stock.quant']._update_available_quantity(self.product, self.warehouse.lot_stock_id, 10)
        pending = self._pending()
        pending.action_create_stock_moves()
        holding = pending.collection_line_ids.stock_move_id.picking_id
        self.assertEqual(holding.document_source_pending_id, pending)
        self._assert_sources(holding, pending)
        wizard = self.env['collect.pending.items.wizard'].create({'pending_collection_id': pending.id})
        returned = wizard._create_return_stock_move(pending.collection_line_ids, 1)
        self.assertEqual(returned.document_source_pending_id, pending)
        self._assert_sources(returned, pending)
        pending.action_cancel()
        cancelled = self.env['stock.picking'].search([
            ('origin', '=', f'Return: {pending.name}'),
            ('company_id', '=', pending.company_id.id),
        ])
        self.assertTrue(cancelled)
        self.assertEqual(cancelled.document_source_pending_id, pending)
        self._assert_sources(cancelled, pending)

    def test_exact_legacy_formats(self):
        pending = self._pending()
        for origin in self.env['stock.picking']._pending_source_origins(pending):
            picking = self._picking(origin=origin)
            self._assert_sources(picking, pending)
            self.assertFalse(picking.document_source_pending_id, 'Discovery must not backfill records')
        self.assertFalse(self._picking(origin=f'Unknown prefix {pending.name}').source_link_data)

    def test_legacy_ambiguous_reference(self):
        pending = self._pending(name='Duplicate pending source')
        self._pending(name=pending.name)
        picking = self._picking(origin=f'Collection: {pending.name}')
        self.assertFalse(picking.source_link_data)

    def test_restricted_pending_does_not_break_stock_form(self):
        pending = self._pending()
        picking = self._picking(document_source_pending_id=pending.id).with_user(self.worker)
        self.assertFalse(picking.source_link_data)

    def test_restricted_stock_user_can_copy_transfer(self):
        pending = self._pending()
        picking = self._picking(document_source_pending_id=pending.id)
        copied = picking.with_user(self.worker).copy()
        self.assertEqual(copied.document_source_pending_id.id, pending.id)
        self.assertFalse(copied.source_link_data)

    def test_cross_company_relation_rejected(self):
        pending = self._pending()
        company = self.env['res.company'].create({'name': 'Pending other company'})
        self.env.user.company_ids |= company
        companies = [self.env.company.id, company.id]
        warehouse = self.env['stock.warehouse'].with_context(allowed_company_ids=companies).search([
            ('company_id', '=', company.id),
        ], limit=1)
        self.assertTrue(warehouse)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['stock.picking'].with_context(allowed_company_ids=companies).create({
                'picking_type_id': warehouse.int_type_id.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': warehouse.lot_stock_id.id,
                'document_source_pending_id': pending.id,
            })

    def test_context_capture_does_not_tag_unrelated_transfer(self):
        pending = self._pending()
        picking = self.env['stock.picking'].with_context(document_source_pending_id=pending.id).create({
            'picking_type_id': self.warehouse.int_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.holding.id, 'origin': 'Unrelated operation',
        })
        self.assertFalse(picking.document_source_pending_id)
