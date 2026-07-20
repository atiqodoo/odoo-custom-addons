from odoo.tests.common import TransactionCase

from ..services.promotion_registry import get_calculator


class TestGammaCalculator(TransactionCase):

    def test_factory_tint_invoice_2600803(self):
        result = get_calculator('gamma_paints').calculate_unit(
            quantity=6,
            list_unit_price=357,
            discount_percentage=40,
            tint_percentage=7,
        )
        self.assertAlmostEqual(result['gross_total'], 2142.0)
        self.assertAlmostEqual(result['discount_amount'], 856.8)
        self.assertAlmostEqual(result['tint_charge'], 149.94)
        self.assertAlmostEqual(result['subtotal_excl_vat'], 1435.14)
        self.assertAlmostEqual(result['unit_cost_excl_vat'], 239.19)

    def test_gamma_invoice_2600812_discount(self):
        result = get_calculator('gamma_paints').calculate_unit(
            quantity=22,
            list_unit_price=13658,
            discount_percentage=42,
            tint_percentage=0,
        )
        self.assertAlmostEqual(result['subtotal_excl_vat'], 174276.08)
        self.assertAlmostEqual(result['unit_cost_excl_vat'], 7921.64)

    def test_showroom_tint_is_based_on_gross(self):
        result = get_calculator('gamma_paints').calculate_unit(
            quantity=2,
            list_unit_price=1000,
            discount_percentage=20,
            tint_percentage=15,
        )
        self.assertAlmostEqual(result['discount_amount'], 400)
        self.assertAlmostEqual(result['tint_charge'], 300)
        self.assertAlmostEqual(result['subtotal_excl_vat'], 1900)
