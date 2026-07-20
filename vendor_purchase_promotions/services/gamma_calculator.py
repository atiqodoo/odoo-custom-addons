import logging

from .base_calculator import VendorCalculator
from .promotion_registry import register_calculator


_logger = logging.getLogger(__name__)


class GammaCalculator(VendorCalculator):
    profile = 'gamma_paints'

    TINT_RATES = {
        'not_tinted': 0.0,
        'factory': 7.0,
        'showroom_branch': 15.0,
    }

    def calculate_unit(
        self,
        *,
        quantity,
        list_unit_price,
        discount_percentage=0.0,
        tint_percentage=0.0,
    ):
        quantity = float(quantity or 0.0)
        list_unit_price = float(list_unit_price or 0.0)
        discount_percentage = float(discount_percentage or 0.0)
        tint_percentage = float(tint_percentage or 0.0)

        if quantity < 0 or list_unit_price < 0:
            raise ValueError('Gamma quantity and list unit price cannot be negative.')
        if not 0.0 <= discount_percentage <= 100.0:
            raise ValueError('Gamma discount must be between 0 and 100 percent.')
        if tint_percentage < 0:
            raise ValueError('Gamma tint percentage cannot be negative.')

        gross_total = quantity * list_unit_price
        discount_amount = gross_total * discount_percentage / 100.0
        tint_charge = gross_total * tint_percentage / 100.0
        subtotal_excl_vat = gross_total - discount_amount + tint_charge
        unit_cost_excl_vat = subtotal_excl_vat / quantity if quantity else 0.0

        result = {
            'gross_total': gross_total,
            'discount_amount': discount_amount,
            'tint_charge': tint_charge,
            'subtotal_excl_vat': subtotal_excl_vat,
            'unit_cost_excl_vat': unit_cost_excl_vat,
        }
        _logger.debug(
            '[VPP_GAMMA_CALC] qty=%s list_unit=%s discount_pct=%s tint_pct=%s result=%s',
            quantity,
            list_unit_price,
            discount_percentage,
            tint_percentage,
            result,
        )
        return result


register_calculator(GammaCalculator())

