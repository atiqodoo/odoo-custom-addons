from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, new_test_user, tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestVendorPriceBasis(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['decimal.precision'].search([('name', '=', 'Product Price')]).digits = 6
        for document in ('rfq', 'lpo', 'receipt', 'invoice'):
            cls.env['ir.config_parameter'].set_param(
                'purchase_net_price_compute.vendor_reference_required_' + document, 'False',
            )
        cls.vendor = cls.env['res.partner'].create({
            'name': 'VAT Basis Test Vendor', 'supplier_rank': 1,
            'invoice_variance_allocation_mode': 'none',
            'require_vendor_invoice_final_total': False,
        })
        cls.vat = cls.env['account.tax'].create({
            'name': 'Test Purchase VAT 16%', 'amount': 16.0,
            'amount_type': 'percent', 'type_tax_use': 'purchase',
            'company_id': cls.env.company.id,
        })
        cls.bill_product = cls.env['product.product'].create({
            'name': 'VAT Basis Brush', 'type': 'service', 'purchase_method': 'receive',
            'supplier_taxes_id': [Command.set(cls.vat.ids)],
            'property_account_expense_id': cls.company_data['default_account_expense'].id,
        })

    def _make_order(self, tax=None, vendor=None, qty=24):
        order = self.env['purchase.order'].create({
            'partner_id': (vendor or self.vendor).id,
            'currency_id': self.env.company.currency_id.id,
            'order_line': [Command.create({
                'product_id': self.bill_product.id, 'name': self.bill_product.name,
                'product_qty': qty, 'product_uom': self.bill_product.uom_po_id.id,
                'price_unit': 22, 'date_planned': fields.Datetime.now(),
                'taxes_id': [Command.set((tax if tax is not None else self.vat).ids)],
            })],
        })
        order.button_confirm()
        order.order_line.qty_received = qty
        return order

    def _make_wizard(self, order=None, basis='included', price=26):
        order = order or self._make_order()
        wizard = self.env['vendor.price.wizard'].create({
            'purchase_id': order.id, 'vendor_price_basis': basis,
        })
        self.env['vendor.price.wizard.line'].create({
            'wizard_id': wizard.id, 'purchase_line_id': order.order_line.id,
            'product_id': self.bill_product.id, 'product_qty': order.order_line.qty_received,
            'price_unit': order.order_line.price_unit, 'vendor_price': price,
            'currency_id': order.currency_id.id,
        })
        return wizard

    def _create_bill(self, wizard):
        action = wizard.action_create_bill()
        return self.env['account.move'].browse(action['res_id'])

    def test_inclusive_price_bill_and_audit(self):
        wizard = self._make_wizard()
        self.assertAlmostEqual(wizard.line_ids._get_effective_bill_unit_price(), 26 / 1.16, places=8)
        self.assertEqual(wizard.invoice_total_vat_incl, 624)
        bill = self._create_bill(wizard)
        self.assertEqual(bill.amount_total, 624)
        self.assertEqual(bill.amount_untaxed, 537.93)
        self.assertEqual(bill.amount_tax, 86.07)
        self.assertEqual(bill.invoice_line_ids.tax_ids, self.vat)
        self.assertEqual(bill.invoice_line_ids.wizard_vendor_list_unit_price, 26)
        self.assertEqual(bill.invoice_line_ids.wizard_vendor_price_basis, 'included')
        self.assertAlmostEqual(bill.invoice_line_ids.price_unit, 26 / 1.16, places=6)
        bill.invoice_date = fields.Date.today()
        self.env['ir.attachment'].create({
            'name': 'test-invoice.txt', 'datas': 'dGVzdA==',
            'res_model': 'account.move', 'res_id': bill.id,
        })
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertAlmostEqual(sum(bill.line_ids.mapped('balance')), 0, places=2)

    def test_exclusive_entry_preserves_existing_calculation(self):
        wizard = self._make_wizard(basis='excluded', price=100)
        wizard.line_ids.write({'applied_discount': 10, 'applied_freight': 5})
        self.assertEqual(wizard.line_ids._get_effective_bill_unit_price(), 94.5)
        self.assertEqual(self._create_bill(wizard).invoice_line_ids.wizard_vendor_price_basis, 'excluded')

    def test_inclusive_adjustments_applied_once(self):
        wizard = self._make_wizard(price=116)
        wizard.line_ids.write({'applied_discount': 10, 'applied_freight': 5})
        self.assertAlmostEqual(wizard.line_ids._get_effective_bill_unit_price(), 94.5)
        bill = self._create_bill(wizard)
        self.assertAlmostEqual(bill.invoice_line_ids.price_unit, 94.5)
        self.assertEqual(bill.invoice_line_ids.discount, 0)

    def test_invoice_total_allocation_follows_normalization_and_acknowledgement(self):
        self.vendor.invoice_variance_allocation_mode = 'absorb_into_cost'
        wizard = self._make_wizard()
        wizard.vendor_invoice_final_total = 620
        self.assertEqual(wizard.invoice_total_vat_incl, 624)
        with self.assertRaises(ValidationError):
            wizard.action_create_bill()
        wizard.action_dismiss_invoice_variance_warning()
        bill = self._create_bill(wizard)
        self.assertEqual(bill.amount_total, 620)
        self.assertEqual(bill.invoice_line_ids.wizard_vendor_list_unit_price, 26)
        self.assertEqual(bill.invoice_line_ids.wizard_vendor_price_basis, 'included')
        self.assertAlmostEqual(bill.invoice_line_ids.wizard_computed_unit_excl_vat, 26 / 1.16)

    def test_switching_basis_keeps_input_and_invalidates_approvals(self):
        wizard = self._make_wizard()
        wizard.write({'promised_cost_discrepancy_approved': True, 'variance_warning_dismiss_count': 2})
        wizard.vendor_price_basis = 'excluded'
        self.assertEqual(wizard.line_ids.vendor_price, 26)
        self.assertFalse(wizard.promised_cost_discrepancy_approved)
        self.assertEqual(wizard.variance_warning_dismiss_count, 0)
        self.assertEqual(wizard.line_ids._get_effective_bill_unit_price(), 26)
        wizard.vendor_price_basis = 'included'
        self.assertEqual(wizard.invoice_total_vat_incl, 624)

    def test_line_edit_invalidates_approvals(self):
        wizard = self._make_wizard()
        wizard.write({'promised_cost_discrepancy_approved': True, 'variance_warning_dismiss_count': 2})
        wizard.line_ids.vendor_price = 29
        self.assertFalse(wizard.promised_cost_discrepancy_approved)
        self.assertEqual(wizard.variance_warning_dismiss_count, 0)

    def test_vendor_default_and_commercial_contact(self):
        self.vendor.vendor_bill_price_basis = 'included'
        contact = self.env['res.partner'].create({'name': 'Invoice Contact', 'parent_id': self.vendor.id})
        self.assertEqual(contact.get_vendor_bill_price_basis(), 'included')
        wizard = self._make_wizard()
        self.assertTrue(wizard.supports_vendor_price_basis)
        self.assertEqual(wizard._get_price_basis_vendor(), self.vendor)
        if wizard._name == 'vendor.price.wizard':
            values = {'purchase_id': wizard.purchase_id.id}
        else:
            values = {
                'partner_id': self.vendor.id, 'company_id': self.env.company.id,
                'currency_id': wizard.currency_id.id,
                'purchase_ids': [Command.set(wizard.purchase_ids.ids)],
                'vendor_invoice_profile': 'standard',
            }
        defaulted = self.env[wizard._name].create(values)
        self.assertEqual(defaulted.vendor_price_basis, 'included')

    def test_tax_edit_invalidates_approval_on_validation(self):
        wizard = self._make_wizard()
        wizard.promised_cost_discrepancy_approved = True
        wizard._remember_price_basis_review()
        self.vat.amount = 20
        wizard._validate_price_basis()
        self.assertFalse(wizard.promised_cost_discrepancy_approved)

    def test_stale_received_quantity_rejected(self):
        wizard = self._make_wizard()
        wizard.line_ids.purchase_line_id.qty_received = 12
        with self.assertRaisesRegex(ValidationError, 'quantities changed'):
            wizard.action_create_bill()

    def test_crown_formula_calculation_preserved(self):
        self.vendor.vendor_invoice_profile = 'crown_paints'
        wizard = self._make_wizard(basis='excluded', price=100)
        wizard.line_ids.write({'vendor_line_total': 1920, 'applied_freight': 5})
        # Preserve Crown's existing structured-discount and freight calculator.
        from odoo.addons.vendor_price_check.services.crown_invoice_calculator import calculate_line
        expected = calculate_line(24, 100, 1920, 5)['preliminary_unit_excl_vat']
        self.assertAlmostEqual(wizard.line_ids._get_effective_bill_unit_price(), expected)

    def test_other_company_tax_rejected(self):
        other = self.env['res.company'].create({
            'name': 'Other VAT Basis Company', 'country_id': self.env.company.country_id.id,
        })
        self.env.user.sudo().write({'company_ids': [Command.link(other.id)]})
        group = self.env['account.tax.group'].create({'name': 'Other VAT', 'company_id': other.id})
        other_tax = self.env['account.tax'].with_company(other).create({
            'name': 'Other company VAT', 'amount': 16, 'type_tax_use': 'purchase',
            'company_id': other.id, 'tax_group_id': group.id,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._make_wizard(self._make_order(tax=other_tax)).action_create_bill()

    def test_zero_rated_tax(self):
        zero_tax = self.vat.copy({'name': 'Explicit zero rate', 'amount': 0})
        wizard = self._make_wizard(self._make_order(tax=zero_tax))
        self.assertEqual(wizard.line_ids._get_effective_bill_unit_price(), 26)
        self.assertEqual(self._create_bill(wizard).amount_total, 624)

    def test_different_line_taxes_and_repeated_product(self):
        wizard = self._make_wizard()
        first_line = wizard.line_ids
        other_tax = self.vat.copy({'name': 'Test purchase VAT 8%', 'amount': 8})
        purchase_line = first_line.purchase_line_id.copy({
            'taxes_id': [Command.set(other_tax.ids)], 'price_unit': 100,
        })
        purchase_line.qty_received = 24
        first_line.copy({'purchase_line_id': purchase_line.id, 'vendor_price': 108})
        bill = self._create_bill(wizard)
        self.assertEqual(bill.amount_total, 3216)
        self.assertEqual(len(bill.invoice_line_ids), 2)
        self.assertAlmostEqual(
            bill.invoice_line_ids.filtered(lambda line: line.purchase_line_id == purchase_line).price_unit,
            100,
        )

    def test_missing_tax_rejected(self):
        with self.assertRaisesRegex(ValidationError, 'Configure purchase taxes'), self.cr.savepoint():
            wizard = self._make_wizard(self._make_order(tax=self.env['account.tax']))
            wizard.action_create_bill()

    def test_included_tax_configuration_rejected(self):
        tax = self.vat.copy({'name': 'Included test tax', 'price_include_override': 'tax_included'})
        with self.assertRaisesRegex(ValidationError, 'tax-excluded'), self.cr.savepoint():
            wizard = self._make_wizard(self._make_order(tax=tax))
            wizard.action_create_bill()

    def test_insufficient_native_precision_rejected(self):
        self.env['decimal.precision'].search([('name', '=', 'Product Price')]).digits = 2
        wizard = self._make_wizard()
        with self.assertRaisesRegex(ValidationError, 'Product Price precision'):
            wizard.action_create_bill()

    def test_formula_vendor_cannot_enable_inclusive_entry(self):
        self.vendor.vendor_invoice_profile = 'crown_paints'
        wizard = self._make_wizard(basis='excluded')
        self.assertFalse(wizard.supports_vendor_price_basis)
        self.assertEqual(wizard._get_price_basis_audit_value(), 'profile')
        with self.assertRaisesRegex(ValidationError, 'vendor invoice formula'), self.cr.savepoint():
            wizard.vendor_price_basis = 'included'

    def test_partial_receipt_quantity(self):
        order = self._make_order()
        order.order_line.qty_received = 12
        wizard = self._make_wizard(order)
        bill = self._create_bill(wizard)
        self.assertEqual(bill.invoice_line_ids.quantity, 12)
        # Odoo's configured per-line rounding: 268.97 base + 43.04 tax.
        self.assertEqual(bill.amount_total, 312.01)
        self.assertEqual(wizard.invoice_total_vat_incl, bill.amount_total)
        self.assertEqual(bill.invoice_line_ids.wizard_vendor_list_unit_price * 12, 312)

    def test_partial_receipt_global_rounding(self):
        self.env.company.tax_calculation_rounding_method = 'round_globally'
        order = self._make_order()
        order.order_line.qty_received = 12
        wizard = self._make_wizard(order)
        self.assertEqual(self._create_bill(wizard).amount_total, 312)

    def test_bill_uses_source_company_with_other_company_active(self):
        wizard = self._make_wizard()
        other = self.env.ref('base.main_company')
        self.assertNotEqual(other, self.env.company)
        self.env.user.sudo().write({'company_ids': [Command.link(other.id)]})
        bill = self._create_bill(wizard.with_context(
            allowed_company_ids=[other.id, self.env.company.id],
        ))
        self.assertEqual(bill.company_id, wizard.line_ids.purchase_line_id.company_id)
        self.assertEqual(bill.amount_total, 624)

    def test_unauthorized_user_cannot_create_wizard(self):
        user = new_test_user(self.env, login='basis_no_purchase', groups='base.group_user')
        with self.assertRaises(AccessError):
            self.env[self._make_wizard()._name].with_user(user).create({})

    def test_wizard_view_loads(self):
        wizard = self._make_wizard()
        with Form(wizard) as form:
            form.vendor_price_basis = 'excluded'
        self.assertEqual(wizard.line_ids.vendor_price, 26)
