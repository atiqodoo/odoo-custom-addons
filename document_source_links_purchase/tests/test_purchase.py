from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseSourceLinks(TransactionCase):
    def test_merged_purchase_sources_and_return(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        partner = self.env['res.partner'].create({'name': 'Source supplier'})
        product = self.env['product.product'].create({'name': 'Source purchase product'})
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.in_type_id.id,
            'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': warehouse.lot_stock_id.id,
        })
        orders = self.env['purchase.order']
        for index in range(2):
            order = self.env['purchase.order'].create({'partner_id': partner.id})
            line = self.env['purchase.order.line'].create({
                'order_id': order.id, 'product_id': product.id, 'name': product.name,
                'product_qty': 1, 'product_uom': product.uom_id.id,
                'price_unit': 1, 'date_planned': fields.Datetime.now(),
            })
            self.env['stock.move'].create({
                'name': product.name, 'product_id': product.id, 'product_uom_qty': 1,
                'product_uom': product.uom_id.id, 'purchase_line_id': line.id,
                'picking_id': picking.id, 'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
            })
            orders |= order
        self.assertEqual({s['id'] for s in picking.source_link_data if s['model'] == 'purchase.order'}, set(orders.ids))
        returned = picking.copy({'move_ids': [], 'return_id': picking.id})
        self.assertEqual({s['id'] for s in returned.source_link_data if s['model'] == 'purchase.order'}, set(orders.ids))
