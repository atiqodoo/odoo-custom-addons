# -*- coding: utf-8 -*-


def wizard_payload(wizard):
    return {
        'wizard_id': wizard.id,
        'vendor_id': wizard.partner_id.id,
        'purchase_ids': wizard.purchase_ids.ids,
        'profile': wizard.vendor_invoice_profile,
        'line_count': len(wizard.line_ids),
        'calculated_total': wizard.invoice_total_vat_incl,
        'vendor_total': wizard.vendor_invoice_final_total,
    }


def line_payload(line):
    return {
        'wizard_line_id': line.id,
        'purchase_id': line.purchase_id.id,
        'po': line.purchase_id.name,
        'purchase_line_id': line.purchase_line_id.id,
        'product_id': line.product_id.id,
        'qty': line.product_qty,
        'vendor_price': line.vendor_price,
        'unit_excl': line.bill_unit_price_excl_vat,
        'unit_vat_incl': line.unit_price_vat_incl,
        'vendor_promised_cost_vat_incl': line.vendor_promised_cost_vat_incl,
        'promised_cost_difference_vat_incl': line.promised_cost_difference_vat_incl,
        'line_total_vat_incl': line.final_line_total_vat_incl or line.line_total_vat_incl,
    }
