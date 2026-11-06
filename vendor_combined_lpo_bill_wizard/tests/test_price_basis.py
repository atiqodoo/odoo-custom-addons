from odoo import Command
from odoo.tests import tagged
from odoo.addons.vendor_price_check.tests.test_vendor_price_basis import TestVendorPriceBasis


@tagged('post_install', '-at_install')
class TestCombinedVendorPriceBasis(TestVendorPriceBasis):
    allow_inherited_tests_method = True
    def _make_wizard(self, order=None, basis='included', price=26):
        order = order or self._make_order()
        wizard = self.env['combined.lpo.bill.wizard'].create({
            'partner_id': order.partner_id.commercial_partner_id.id,
            'company_id': order.company_id.id, 'currency_id': order.currency_id.id,
            'purchase_ids': [Command.set(order.ids)],
            'vendor_invoice_profile': order.partner_id.get_vendor_invoice_profile(),
            'vendor_price_basis': basis,
        })
        wizard.action_reload_lines()
        wizard.line_ids.vendor_price = price
        return wizard

    def test_multiple_lpos_same_basis(self):
        first = self._make_order(qty=12)
        second = self._make_order(qty=24)
        wizard = self._make_wizard(first)
        wizard.purchase_ids = first | second
        wizard.action_reload_lines()
        wizard.line_ids.vendor_price = 26
        bill = self._create_bill(wizard)
        # Preserve the company's native per-line rounding for the 12-unit line.
        self.assertEqual(bill.amount_total, 936.01)
        self.assertEqual(len(bill.invoice_line_ids), 2)
        self.assertEqual(set(bill.invoice_line_ids.mapped('wizard_vendor_price_basis')), {'included'})

    def test_gamma_formula_and_selector_restriction(self):
        from odoo.exceptions import ValidationError
        self.vendor.vendor_invoice_profile = 'gamma_paints'
        wizard = self._make_wizard(basis='excluded', price=100)
        wizard.line_ids.write({'applied_discount': 40, 'gamma_tint_percentage': 7})
        self.assertAlmostEqual(wizard.line_ids._get_effective_bill_unit_price(), 67)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.vendor_price_basis = 'included'

    def test_normal_gamma_formula_preserved(self):
        self.vendor.vendor_invoice_profile = 'gamma_paints'
        wizard = super()._make_wizard(basis='excluded', price=100)
        wizard.line_ids.write({'applied_discount': 40, 'gamma_tint_percentage': 7})
        self.assertAlmostEqual(wizard.line_ids._get_effective_bill_unit_price(), 67)
        self.assertFalse(wizard.supports_vendor_price_basis)
