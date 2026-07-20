# -*- coding: utf-8 -*-
"""Pure Crown invoice arithmetic, isolated from Odoo models for easy testing."""
import logging


_logger = logging.getLogger(__name__)


def calculate_line(quantity, invoice_unit_price, vendor_line_total, freight_percentage):
    quantity = quantity or 0.0
    invoice_unit_price = invoice_unit_price or 0.0
    vendor_line_total = vendor_line_total or 0.0
    freight_percentage = freight_percentage or 0.0

    expected_total = quantity * invoice_unit_price
    structured_discount_amount = expected_total - vendor_line_total
    structured_discount_percentage = (
        structured_discount_amount / expected_total * 100.0 if expected_total else 0.0
    )
    discount_per_quantity = structured_discount_amount / quantity if quantity else 0.0
    freight_amount = vendor_line_total * freight_percentage / 100.0
    preliminary_total_excl_vat = vendor_line_total + freight_amount
    preliminary_unit_excl_vat = (
        preliminary_total_excl_vat / quantity if quantity else 0.0
    )

    result = {
        'expected_total': expected_total,
        'structured_discount_amount': structured_discount_amount,
        'structured_discount_percentage': structured_discount_percentage,
        'discount_per_quantity': discount_per_quantity,
        'freight_amount': freight_amount,
        'preliminary_total_excl_vat': preliminary_total_excl_vat,
        'preliminary_unit_excl_vat': preliminary_unit_excl_vat,
    }
    _logger.debug(
        '[VPC_CROWN_CALC] line quantity=%s unit=%s line_total=%s freight_pct=%s result=%s',
        quantity,
        invoice_unit_price,
        vendor_line_total,
        freight_percentage,
        result,
    )
    return result


def calculate_variance(calculated_total, vendor_final_total):
    calculated_total = calculated_total or 0.0
    vendor_final_total = vendor_final_total or 0.0
    variance_amount = calculated_total - vendor_final_total
    variance_percentage = (
        variance_amount / calculated_total * 100.0 if calculated_total else 0.0
    )
    allocation_ratio = (
        vendor_final_total / calculated_total
        if calculated_total and vendor_final_total
        else 1.0
    )
    result = {
        'variance_amount': variance_amount,
        'variance_percentage': variance_percentage,
        'allocation_ratio': allocation_ratio,
    }
    _logger.debug(
        '[VPC_CROWN_CALC] variance calculated_total=%s vendor_final_total=%s result=%s',
        calculated_total,
        vendor_final_total,
        result,
    )
    return result
