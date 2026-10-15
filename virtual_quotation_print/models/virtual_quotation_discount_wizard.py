# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class VirtualQuotationDiscountWizard(models.TransientModel):
    _name = 'virtual.quotation.discount.wizard'
    _description = 'Virtual Quotation Discount Wizard'
    _inherit = 'virtual.quotation.log.mixin'

    quotation_id = fields.Many2one(
        'virtual.quotation',
        default=lambda self: self.env.context.get('active_id'),
        required=True,
    )
    company_id = fields.Many2one(related='quotation_id.company_id')
    currency_id = fields.Many2one(related='quotation_id.currency_id')
    discount_amount = fields.Monetary(string='Amount')
    discount_percentage = fields.Float(string='Percentage')
    discount_type = fields.Selection(
        selection=[
            ('sol_discount', 'On All Order Lines'),
            ('so_discount', 'Global Discount'),
            ('amount', 'Fixed Amount'),
        ],
        default='sol_discount',
        required=True,
    )

    @api.constrains('discount_type', 'discount_percentage')
    def _check_discount_percentage(self):
        for wizard in self:
            if (
                wizard.discount_type in ('sol_discount', 'so_discount')
                and not 0.0 <= wizard.discount_percentage <= 1.0
            ):
                raise ValidationError(_('Invalid discount amount.'))

    @api.constrains('discount_type', 'discount_amount')
    def _check_discount_amount(self):
        for wizard in self:
            if wizard.discount_type == 'amount' and wizard.discount_amount < 0.0:
                raise ValidationError(_('Discount amount cannot be negative.'))

    def action_apply_discount(self):
        self.ensure_one()
        self.quotation_id._ensure_draft()
        self = self.with_company(self.company_id)
        self._vq_log(
            'DISCOUNT APPLY START',
            quotation_id=self.quotation_id.id,
            discount_type=self.discount_type,
            discount_percentage=self.discount_percentage,
            discount_amount=self.discount_amount,
        )
        if self.discount_type == 'sol_discount':
            self._apply_line_discount()
        else:
            self._replace_discount_lines()
            self._create_discount_lines()
        self._vq_log(
            'DISCOUNT APPLY DONE',
            quotation_id=self.quotation_id.id,
            total=self.quotation_id.amount_total,
        )
        return {'type': 'ir.actions.act_window_close'}

    def _apply_line_discount(self):
        target_lines = self._get_discountable_lines()
        self._replace_discount_lines()
        target_lines.write({'discount': self.discount_percentage * 100.0})

    def _create_discount_lines(self):
        discount_percentage = self._get_global_discount_percentage()
        if not discount_percentage:
            return

        grouped_amounts = self._get_discount_base_amounts_by_taxes()
        if not grouped_amounts:
            return

        values_list = []
        for taxes, subtotal in grouped_amounts.items():
            values_list.append(
                self._prepare_discount_line_values(
                    amount=subtotal * discount_percentage,
                    taxes=taxes,
                    description=self._get_discount_line_description(),
                )
            )
        self.env['virtual.quotation.line'].create(values_list)

    def _get_global_discount_percentage(self):
        if self.discount_type == 'so_discount':
            return self.discount_percentage
        total = self._get_discountable_total_amount()
        if not total:
            return 0.0
        return min(self.discount_amount / total, 1.0)

    def _get_discount_base_amounts_by_taxes(self):
        totals = defaultdict(float)
        for line in self._get_discountable_lines():
            if not line.product_uom_qty or not line.price_unit:
                continue
            taxes = line.tax_id.flatten_taxes_hierarchy()
            taxes -= taxes.filtered(lambda tax: tax.amount_type == 'fixed')
            base_amount = line.price_unit * (1.0 - (line.discount or 0.0) / 100.0) * line.product_uom_qty
            totals[taxes] += base_amount
        return totals

    def _get_discountable_total_amount(self):
        total = self.quotation_id.amount_total
        for line in self._get_discountable_lines():
            fixed_taxes = line.tax_id.flatten_taxes_hierarchy().filtered(lambda tax: tax.amount_type == 'fixed')
            total -= sum(fixed_taxes.mapped('amount')) * line.product_uom_qty
        return max(total, 0.0)

    def _get_discountable_lines(self):
        return self.quotation_id.line_ids.filtered(
            lambda line: (
                not line.display_type
                and not line.is_discount_line
                and line.product_uom_qty
                and line.price_unit
            )
        )

    def _replace_discount_lines(self):
        discount_lines = self.quotation_id.line_ids.filtered('is_discount_line')
        if discount_lines:
            discount_lines.unlink()

    def _prepare_discount_line_values(self, amount, taxes, description):
        self.ensure_one()
        discount_product = self._get_configured_discount_product()
        values = {
            'quotation_id': self.quotation_id.id,
            'sequence': self.quotation_id._get_next_line_sequence(),
            'name': description,
            'product_uom_qty': 1.0,
            'price_unit': -amount,
            'discount': 0.0,
            'tax_id': [(6, 0, taxes.ids)],
            'is_manual_item': not bool(discount_product),
            'is_discount_line': True,
        }
        if discount_product:
            values.update({
                'product_id': discount_product.id,
                'product_uom_id': discount_product.uom_id.id,
            })
        return values

    def _get_discount_line_description(self):
        self.ensure_one()
        discount_product = self._get_configured_discount_product()
        if discount_product:
            return (
                discount_product.get_product_multiline_description_sale()
                or discount_product.display_name
            )
        return _('Discount')

    def _get_configured_discount_product(self):
        self.ensure_one()
        if 'sale_discount_product_id' not in self.company_id._fields:
            return self.env['product.product']
        return self.company_id.sale_discount_product_id
