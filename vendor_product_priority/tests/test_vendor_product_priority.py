from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestVendorProductPriority(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor_a = cls.env['res.partner'].create({
            'name': 'VPS Vendor A',
            'supplier_rank': 1,
            'vendor_invoice_profile': 'gamma_paints',
        })
        cls.vendor_b = cls.env['res.partner'].create({
            'name': 'VPS Vendor B',
            'supplier_rank': 1,
            'vendor_invoice_profile': 'gamma_paints',
        })
        cls.vendor_c = cls.env['res.partner'].create({
            'name': 'VPS Vendor C',
            'supplier_rank': 1,
            'vendor_invoice_profile': 'gamma_paints',
        })
        cls.primary_a = cls.env['product.product'].create({
            'name': 'VPS Search Product Primary A',
            'default_code': 'VPS-A-PRIMARY',
            'purchase_ok': True,
            'available_in_pos': True,
        })
        cls.secondary_a = cls.env['product.product'].create({
            'name': 'VPS Search Product Secondary A',
            'default_code': 'VPS-A-SECONDARY',
            'purchase_ok': True,
            'available_in_pos': True,
        })
        cls.unmapped = cls.env['product.product'].create({
            'name': 'VPS Search Product Unmapped',
            'default_code': 'VPS-UNMAPPED',
            'purchase_ok': True,
            'available_in_pos': True,
        })

        supplierinfo = cls.env['product.supplierinfo']
        # Vendor A is primary for primary_a.
        supplierinfo.create({
            'partner_id': cls.vendor_a.id,
            'product_tmpl_id': cls.primary_a.product_tmpl_id.id,
            'product_id': cls.primary_a.id,
            'sequence': 1,
            'min_qty': 0,
            'price': 100,
        })
        supplierinfo.create({
            'partner_id': cls.vendor_b.id,
            'product_tmpl_id': cls.primary_a.product_tmpl_id.id,
            'product_id': cls.primary_a.id,
            'sequence': 2,
            'min_qty': 0,
            'price': 90,
        })
        # Vendor A has two price tiers here but remains one distinct secondary
        # vendor after Vendor B.
        supplierinfo.create({
            'partner_id': cls.vendor_b.id,
            'product_tmpl_id': cls.secondary_a.product_tmpl_id.id,
            'product_id': cls.secondary_a.id,
            'sequence': 1,
            'min_qty': 0,
            'price': 80,
        })
        supplierinfo.create({
            'partner_id': cls.vendor_a.id,
            'product_tmpl_id': cls.secondary_a.product_tmpl_id.id,
            'product_id': cls.secondary_a.id,
            'sequence': 2,
            'min_qty': 0,
            'price': 70,
        })
        supplierinfo.create({
            'partner_id': cls.vendor_a.id,
            'product_tmpl_id': cls.secondary_a.product_tmpl_id.id,
            'product_id': cls.secondary_a.id,
            'sequence': 2,
            'min_qty': 50,
            'price': 60,
        })
        supplierinfo.create({
            'partner_id': cls.vendor_c.id,
            'product_tmpl_id': cls.secondary_a.product_tmpl_id.id,
            'product_id': cls.secondary_a.id,
            'sequence': 3,
            'min_qty': 0,
            'price': 50,
        })

    def _priority_context(self, vendor=None, source='test'):
        return {
            'vendor_priority_search': True,
            'vendor_priority_source': source,
            'partner_id': (vendor or self.vendor_a).id,
            'company_id': self.env.company.id,
        }

    def test_variant_mapping_uses_distinct_vendor_position(self):
        product = self.secondary_a.with_context(company=self.env.company.id)
        self.assertEqual(product.vps_primary_vendor_id, self.vendor_b)
        self.assertEqual(product.vps_secondary_vendor_id, self.vendor_a)
        self.assertEqual(product.vps_mapping_state, 'complete')

    def test_template_mapping_is_available(self):
        template = self.primary_a.product_tmpl_id.with_context(company=self.env.company.id)
        self.assertEqual(template.vps_template_primary_vendor_id, self.vendor_a)
        self.assertEqual(template.vps_template_secondary_vendor_id, self.vendor_b)

    def test_name_search_orders_primary_secondary_then_unmapped(self):
        products = self.env['product.product'].with_context(**self._priority_context())
        result = products.name_search(
            'VPS Search Product',
            args=[('id', 'in', [self.primary_a.id, self.secondary_a.id, self.unmapped.id])],
            limit=10,
        )
        self.assertEqual(
            [record_id for record_id, _name in result],
            [self.primary_a.id, self.secondary_a.id, self.unmapped.id],
        )

    def test_exact_unmapped_reference_is_not_buried(self):
        products = self.env['product.product'].with_context(**self._priority_context())
        result = products.name_search(
            'VPS-UNMAPPED',
            args=[('id', 'in', [self.primary_a.id, self.secondary_a.id, self.unmapped.id])],
            limit=10,
        )
        self.assertTrue(result)
        self.assertEqual(result[0][0], self.unmapped.id)

    def test_web_search_read_uses_same_rank_order(self):
        products = self.env['product.product'].with_context(**self._priority_context(source='test_catalog'))
        result = products.web_search_read(
            [('id', 'in', [self.primary_a.id, self.secondary_a.id, self.unmapped.id])],
            {'display_name': {}},
            limit=10,
        )
        self.assertEqual(result['length'], 3)
        self.assertEqual(
            [record['id'] for record in result['records']],
            [self.primary_a.id, self.secondary_a.id, self.unmapped.id],
        )

    def test_catalog_context_is_soft_priority_not_hard_filter(self):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor_a.id,
            'vendor_promised_cost_contact': 'VPS Test Contact',
        })
        context = order._get_action_add_from_catalog_extra_context()
        self.assertTrue(context['vendor_priority_search'])
        self.assertEqual(context['partner_id'], self.vendor_a.id)
        self.assertNotIn('search_default_seller_ids', context)
