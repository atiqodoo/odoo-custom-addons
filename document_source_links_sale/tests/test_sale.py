from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleSourceLinks(TransactionCase):
    def test_sale_delivery(self):
        partner = self.env['res.partner'].create({'name': 'Source sale customer'})
        order = self.env['sale.order'].create({'partner_id': partner.id})
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.out_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'sale_id': order.id,
        })
        self.assertIn(order.id, [s['id'] for s in picking.source_link_data if s['model'] == 'sale.order'])
