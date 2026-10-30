from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestSourceLinks(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.worker = new_test_user(cls.env, login='source_link_worker', groups='stock.group_stock_user')
        cls.plain_user = new_test_user(cls.env, login='source_link_plain', groups='base.group_user')

    def _picking(self, **extra):
        return self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.int_type_id.id,
            'location_id': self.warehouse.lot_stock_id.id,
            'location_dest_id': self.warehouse.lot_stock_id.id,
            **extra,
        })

    def test_manual_transfer_and_forged_target(self):
        picking = self._picking(origin='Unrelated text')
        self.assertFalse(picking.source_link_data)
        with self.assertRaises(AccessError):
            picking.action_open_source_link('res.users', self.env.user.id)

    def test_return_backorder_and_cycle(self):
        original = self._picking()
        second = self._picking(backorder_id=original.id)
        returned = self._picking(return_id=second.id)
        original.backorder_id = returned
        sources = returned._get_visible_source_links()
        self.assertEqual({s['id'] for s in sources}, {original.id, second.id})
        action = returned.action_open_source_link('stock.picking', original.id)
        self.assertEqual(action['res_id'], original.id)
        self.assertEqual(action['context']['form_view_initial_mode'], 'readonly')

    def test_duplicate_and_self_links(self):
        picking, target = self._picking(), self._picking()
        with patch.object(type(picking), '_get_source_link_records',
                          return_value=[('Self', picking), ('First', target), ('Duplicate', target)]):
            self.assertEqual(len(picking._get_visible_source_links()), 1)

    def test_deleted_source_is_omitted(self):
        picking, target = self._picking(), self._picking()
        target.unlink()
        with patch.object(type(picking), '_get_source_link_records', return_value=[('Deleted', target)]):
            self.assertEqual(picking._get_visible_source_links(), [])

    def test_target_rule_checked_again_on_click(self):
        parent, target = self._picking(), self._picking()
        parent = parent.with_user(self.worker)
        self.assertTrue(parent.has_access('read'))
        self.env['ir.rule'].create({
            'name': 'Hide source link target',
            'model_id': self.env['ir.model']._get_id('stock.picking'),
            'domain_force': "[('id', '!=', %s)]" % target.id,
        })
        with patch.object(type(parent), '_get_source_link_records',
                          return_value=[('Hidden', target.with_user(self.worker))]):
            self.assertEqual(parent._get_visible_source_links(), [])
            with self.assertRaises(AccessError):
                parent.action_open_source_link('stock.picking', target.id)

    def test_parent_access_required(self):
        picking = self._picking().with_user(self.plain_user)
        with self.assertRaises(AccessError):
            picking.action_open_source_link('res.partner', self.env.user.partner_id.id)

    def test_cross_company_source_hidden_even_with_both_allowed(self):
        parent = self._picking()
        other = self.env['res.company'].create({'name': 'Source link second company'})
        target = self.env['stock.warehouse'].search([('company_id', '=', other.id)], limit=1)
        parent = parent.with_context(allowed_company_ids=[self.env.company.id, other.id])
        with patch.object(type(parent), '_get_source_link_records', return_value=[('Other company', target)]):
            self.assertEqual(parent._get_visible_source_links(), [])

    def test_no_acl_target_does_not_break_form(self):
        picking = self._picking().with_user(self.worker)
        secret = self.env['ir.config_parameter'].create({'key': 'source_link_test_key', 'value': 'test'})
        with patch.object(type(picking), '_get_source_link_records',
                          return_value=[('Restricted configuration', secret.with_user(self.worker))]):
            self.assertEqual(picking._get_visible_source_links(), [])

    def test_upstream_move_chain(self):
        original, destination = self._picking(), self._picking()
        product = self.env['product.product'].create({'name': 'Source chain product'})
        values = {'name': 'Source chain', 'product_id': product.id, 'product_uom_qty': 1,
                  'product_uom': product.uom_id.id, 'location_id': self.warehouse.lot_stock_id.id,
                  'location_dest_id': self.warehouse.lot_stock_id.id}
        first = self.env['stock.move'].create({**values, 'picking_id': original.id})
        self.env['stock.move'].create({**values, 'picking_id': destination.id,
                                       'move_orig_ids': [(4, first.id)]})
        self.assertIn(original, destination._get_source_link_pickings())
