from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    discount_fixed = fields.Float(
        string='Fixed Discount',
        digits='Product Price',
        default=0.0,
        help='Fixed discount amount applied to the line total'
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        fields_list.append('discount_fixed')
        return fields_list

    def _get_fixed_discount_per_unit(self):
        self.ensure_one()
        if self.qty and self.discount_fixed:
            return self.discount_fixed / abs(self.qty)
        return 0.0

    def _compute_amount_line_all(self):
        self.ensure_one()
        fpos = self.order_id.fiscal_position_id
        tax_ids_after_fiscal_position = fpos.map_tax(self.tax_ids)
        
        price = self.price_unit * (1 - (self.discount or 0.0) / 100.0)
        fixed_discount_per_unit = self._get_fixed_discount_per_unit()
        if fixed_discount_per_unit:
            price = price - fixed_discount_per_unit
        
        taxes = tax_ids_after_fiscal_position.compute_all(
            price, 
            self.order_id.currency_id, 
            self.qty, 
            product=self.product_id, 
            partner=self.order_id.partner_id
        )
        return {
            'price_subtotal_incl': taxes['total_included'],
            'price_subtotal': taxes['total_excluded'],
        }

    @api.onchange('qty', 'discount', 'discount_fixed', 'price_unit', 'tax_ids')
    def _onchange_qty(self):
        if self.product_id:
            price = self.price_unit * (1 - (self.discount or 0.0) / 100.0)
            total_price = price * self.qty
            if self.discount_fixed:
                total_price = total_price - self.discount_fixed
            self.price_subtotal = self.price_subtotal_incl = total_price
            if self.tax_ids:
                fixed_discount_per_unit = self._get_fixed_discount_per_unit()
                unit_price = price - fixed_discount_per_unit
                taxes = self.tax_ids.compute_all(
                    unit_price, 
                    self.order_id.currency_id, 
                    self.qty, 
                    product=self.product_id, 
                    partner=False
                )
                self.price_subtotal = taxes['total_excluded']
                self.price_subtotal_incl = taxes['total_included']

    def _get_discount_amount(self):
        discount_amount = super()._get_discount_amount() if hasattr(super(), '_get_discount_amount') else 0.0
        if self.discount_fixed:
            discount_amount += self.discount_fixed
        return discount_amount
