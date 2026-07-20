# -*- coding: utf-8 -*-
import logging

from odoo import _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class CombinedLpoBillBuilder:
    def __init__(self, wizard):
        self.wizard = wizard

    def _prepare_invoice_line_command(self, line):
        line._validate_for_bill()
        price_unit = line._get_effective_bill_unit_price()
        values = {
            'product_id': line.product_id.id,
            'quantity': line.product_qty,
            'product_uom_id': line.purchase_line_id.product_uom.id,
            'price_unit': price_unit,
            'tax_ids': [(6, 0, line.purchase_line_id.taxes_id.ids)],
            'purchase_line_id': line.purchase_line_id.id,
            'use_custom_pricing': True,
            'net_price': price_unit,
            'applied_discount': line._get_effective_bill_discount(),
            'applied_freight': line.applied_freight,
            'vpc_from_vendor_price_wizard': True,
        }
        values.update(self.wizard._profile_adapter().prepare_bill_line_vals(line))
        _logger.info(
            '[CLPO_LINE] prepare_bill_line wizard_id=%s purchase_line_id=%s po=%s '
            'product_id=%s qty=%s unit_excl=%s',
            self.wizard.id,
            line.purchase_line_id.id,
            line.purchase_id.name,
            line.product_id.id,
            line.product_qty,
            price_unit,
        )
        return (0, 0, values)

    def create_or_update_bill(self):
        wizard = self.wizard
        profile_vals = wizard._profile_adapter().prepare_bill_vals()
        invoice_origin = wizard._get_invoice_origin_text()
        line_commands = [
            self._prepare_invoice_line_command(line)
            for line in wizard.line_ids.filtered(lambda item: item.include_line)
        ]
        if not line_commands:
            raise ValidationError(_('No included combined LPO lines are available to bill.'))

        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': wizard.partner_id.id,
            'invoice_date': wizard.invoice_date,
            'invoice_origin': invoice_origin,
            'ref': wizard.vendor_invoice_reference or False,
            'currency_id': wizard.currency_id.id,
            'invoice_line_ids': line_commands,
            'combined_lpo_bill_source': True,
            'combined_purchase_ids': [(6, 0, wizard.purchase_ids.ids)],
            'combined_lpo_origin_text': invoice_origin,
            'combined_lpo_line_count': len(line_commands),
            'combined_lpo_debug_summary': wizard._format_debug_summary(),
            **profile_vals,
        }
        if len(wizard.purchase_ids) == 1:
            bill_vals['purchase_id'] = wizard.purchase_ids.id

        context = {
            'wizard_vendor_prices': {
                line.product_id.id: line._get_effective_bill_unit_price()
                for line in wizard.line_ids.filtered('include_line')
            },
            'wizard_vendor_prices_by_purchase_line': {
                line.purchase_line_id.id: line._get_effective_bill_unit_price()
                for line in wizard.line_ids.filtered('include_line')
            },
        }

        if wizard.bill_id:
            manual_lines = wizard.bill_id.invoice_line_ids.filtered(
                lambda item: item.display_type not in ('line_section', 'line_note')
                and not item.vpc_from_vendor_price_wizard
            )
            if manual_lines:
                raise ValidationError(_(
                    'This draft bill contains manual product lines. Remove them before updating '
                    'from the combined LPO wizard.'
                ))
            _logger.info(
                '[CLPO_BILL_WRITE] updating_bill wizard_id=%s bill_id=%s line_count=%s',
                wizard.id,
                wizard.bill_id.id,
                len(line_commands),
            )
            wizard.bill_id.with_context(**context).write({
                'invoice_line_ids': [(5, 0, 0)] + line_commands,
                **{key: value for key, value in bill_vals.items() if key != 'invoice_line_ids'},
            })
            bill = wizard.bill_id
        else:
            _logger.info(
                '[CLPO_BILL_BUILD] creating_bill wizard_id=%s vendor_id=%s origins=%s line_count=%s',
                wizard.id,
                wizard.partner_id.id,
                invoice_origin,
                len(line_commands),
            )
            bill = wizard.env['account.move'].with_context(**context).create(bill_vals)

        wizard._validate_created_bill(bill)
        discrepancies = bill.with_context(**context)._check_vendor_bill_prices()
        if hasattr(bill, '_sync_promotion_payment_hold'):
            bill._sync_promotion_payment_hold()

        _logger.info(
            '[CLPO_BILL_BUILD] complete wizard_id=%s bill_id=%s amount_total=%s '
            'discrepancies=%s promotion_hold=%s',
            wizard.id,
            bill.id,
            bill.amount_total,
            discrepancies,
            getattr(bill, 'promotion_payment_hold', False),
        )
        return bill
