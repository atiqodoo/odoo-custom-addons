# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VirtualQuotationService(models.AbstractModel):
    _name = 'virtual.quotation.service'
    _description = 'Virtual Quotation Service'
    _inherit = 'virtual.quotation.log.mixin'

    @api.model
    def load_sale_order_into_virtual_quote(self, sale_order, quotation=False, replace_lines=False):
        self._vq_log(
            'LOAD SALE ORDER START',
            sale_order_id=sale_order.id,
            quotation_id=quotation.id if quotation else False,
            replace_lines=replace_lines,
        )
        if not sale_order:
            raise UserError(_('Select a source quotation.'))
        quotation = quotation.exists() if quotation else self.env['virtual.quotation']
        if quotation:
            quotation._ensure_draft()
            self._sync_quotation_header_from_sale_order(quotation, sale_order)
        else:
            quotation = self.env['virtual.quotation'].create(
                self._prepare_virtual_quote_from_sale_order_values(sale_order)
            )

        if replace_lines:
            quotation.line_ids.unlink()

        created_lines = self.env['virtual.quotation.line']
        for sale_line in sale_order.order_line:
            values = self._prepare_virtual_line_from_sale_line_values(quotation, sale_line)
            created_lines |= self.env['virtual.quotation.line'].create(values)

        quotation.message_post(
            body=_('Loaded %(count)s line(s) from real quotation %(order)s.', count=len(created_lines), order=sale_order.name)
        )
        self._vq_log(
            'LOAD SALE ORDER DONE',
            sale_order_id=sale_order.id,
            quotation_id=quotation.id,
            line_count=len(created_lines),
        )
        return quotation

    @api.model
    def _prepare_virtual_quote_from_sale_order_values(self, sale_order):
        values = {
            'partner_id': sale_order.partner_id.id,
            'linked_sale_order_id': sale_order.id,
            'date_order': fields.Datetime.now(),
            'validity_date': sale_order.validity_date,
            'pricelist_id': sale_order.pricelist_id.id,
            'currency_id': sale_order.currency_id.id,
            'payment_term_id': sale_order.payment_term_id.id,
            'user_id': sale_order.user_id.id or self.env.uid,
            'company_id': sale_order.company_id.id,
            'note': sale_order.note,
        }
        return {key: value for key, value in values.items() if value}

    @api.model
    def _sync_quotation_header_from_sale_order(self, quotation, sale_order):
        values = {
            'partner_id': sale_order.partner_id.id,
            'linked_sale_order_id': sale_order.id,
            'validity_date': sale_order.validity_date,
            'pricelist_id': sale_order.pricelist_id.id,
            'currency_id': sale_order.currency_id.id,
            'payment_term_id': sale_order.payment_term_id.id,
            'company_id': sale_order.company_id.id,
        }
        quotation.write({key: value for key, value in values.items() if value})

    @api.model
    def _prepare_virtual_line_from_sale_line_values(self, quotation, sale_line):
        values = {
            'quotation_id': quotation.id,
            'sequence': sale_line.sequence,
            'display_type': sale_line.display_type,
            'name': sale_line.name or sale_line.product_id.display_name,
        }
        if not sale_line.display_type:
            values.update({
                'product_id': sale_line.product_id.id,
                'is_manual_item': not bool(sale_line.product_id),
                'product_uom_qty': sale_line.product_uom_qty,
                'product_uom_id': sale_line.product_uom.id,
                'price_unit': sale_line.price_unit,
                'discount': sale_line.discount,
                'tax_id': [(6, 0, sale_line.tax_id.ids)],
                'is_discount_line': self._is_sale_discount_line(sale_line),
                'metadata_json': self._prepare_virtual_line_metadata_from_sale_line(sale_line),
            })
        else:
            values.update({
                'product_uom_qty': 0.0,
                'price_unit': 0.0,
                'discount': 0.0,
            })
        extension_values = self._prepare_virtual_line_from_sale_line_extension_values(quotation, sale_line, values)
        values.update(extension_values or {})
        return values

    @api.model
    def _prepare_virtual_line_metadata_from_sale_line(self, sale_line):
        metadata = {
            'source_sale_order_id': sale_line.order_id.id,
            'source_sale_order_name': sale_line.order_id.name,
            'source_sale_order_line_id': sale_line.id,
        }
        optional_fields = [
            'is_tinted_product_line',
            'tinting_formula_json',
            'base_product_id',
            'base_product_uom_id',
            'quoted_cost_at_creation',
            'quoted_base_cost',
            'quoted_colorant_cost',
            'colour_code_id',
            'fandeck_id',
            'base_category_id',
            'tinted_product_created',
            'tinting_formula_version_id',
        ]
        for field_name in optional_fields:
            if field_name not in sale_line._fields:
                continue
            value = sale_line[field_name]
            if not value:
                continue
            if sale_line._fields[field_name].type == 'many2one':
                metadata[field_name] = {
                    'id': value.id,
                    'display_name': value.display_name,
                }
            else:
                metadata[field_name] = value
        return metadata

    @api.model
    def _prepare_virtual_line_from_sale_line_extension_values(self, quotation, sale_line, values):
        return {}

    @api.model
    def _is_sale_discount_line(self, sale_line):
        if 'sale_discount_product_id' not in sale_line.company_id._fields:
            return False
        discount_product = sale_line.company_id.sale_discount_product_id
        return bool(discount_product and sale_line.product_id == discount_product)

    @api.model
    def prepare_product_line_values(self, quotation, product, quantity=1.0):
        self._vq_log(
            'PREPARE PRODUCT LINE START',
            quotation_id=quotation.id,
            product_id=product.id,
            quantity=quantity,
        )
        if not quotation or not product:
            raise UserError(_('Virtual quotation and product are required.'))
        quantity = self._as_float(quantity, 1.0)
        values = {
            'quotation_id': quotation.id,
            'product_id': product.id,
            'name': product.get_product_multiline_description_sale()
            or product.display_name,
            'product_uom_qty': quantity,
            'product_uom_id': product.uom_id.id,
            'price_unit': self._get_product_price(quotation, product, quantity),
            'tax_id': [(6, 0, self._get_product_taxes(product).ids)],
            'is_manual_item': False,
        }
        extra_values = self._prepare_product_line_extension_values(quotation, product, quantity)
        values.update(extra_values or {})
        self._vq_log('PREPARE PRODUCT LINE DONE', values=values)
        return values

    @api.model
    def prepare_manual_line_values(self, quotation, name, quantity=1.0, price_unit=0.0):
        self._vq_log(
            'PREPARE MANUAL LINE START',
            quotation_id=quotation.id,
            name=name,
            quantity=quantity,
            price_unit=price_unit,
        )
        if not quotation:
            raise UserError(_('Virtual quotation is required.'))
        if not name:
            raise UserError(_('Manual item description is required.'))
        values = {
            'quotation_id': quotation.id,
            'name': name,
            'product_uom_qty': self._as_float(quantity, 1.0),
            'price_unit': self._as_float(price_unit, 0.0),
            'is_manual_item': True,
        }
        extra_values = self._prepare_manual_line_extension_values(quotation, values)
        values.update(extra_values or {})
        self._vq_log('PREPARE MANUAL LINE DONE', values=values)
        return values

    @api.model
    def compute_line_amounts(self, line):
        price_unit = self._as_float(line.price_unit)
        quantity = self._as_float(line.product_uom_qty)
        discount = self._as_float(line.discount)
        price = price_unit * (1.0 - (discount / 100.0))
        currency = line.currency_id or line.quotation_id.currency_id or self.env.company.currency_id
        tax_result = line.tax_id.compute_all(
            price,
            currency=currency,
            quantity=quantity,
            product=line.product_id,
            partner=line.quotation_id.partner_id,
        ) if line.tax_id else {
            'total_excluded': price * quantity,
            'total_included': price * quantity,
        }
        return {
            'price_subtotal': currency.round(tax_result.get('total_excluded', 0.0)),
            'price_total': currency.round(tax_result.get('total_included', 0.0)),
            'price_tax': currency.round(
                tax_result.get('total_included', 0.0)
                - tax_result.get('total_excluded', 0.0)
            ),
        }

    @api.model
    def create_real_sale_order(self, quotation):
        self._vq_log('CREATE REAL SALE ORDER START', quotation_id=quotation.id)
        if not quotation.partner_id:
            raise UserError(_('Select a customer before creating a real quotation.'))
        order_values = self._prepare_sale_order_values(quotation)
        order = self.env['sale.order'].create(order_values)
        self._create_sale_order_lines(quotation, order)
        quotation.write({'linked_sale_order_id': order.id})
        order.message_post(
            body=_('Created from virtual quotation %s.') % quotation.display_name
        )
        self._vq_log('CREATE REAL SALE ORDER DONE', quotation_id=quotation.id, order_id=order.id)
        return order

    @api.model
    def _prepare_sale_order_values(self, quotation):
        values = {
            'partner_id': quotation.partner_id.id,
            'origin': quotation.name,
        }
        if quotation.pricelist_id:
            values['pricelist_id'] = quotation.pricelist_id.id
        if quotation.payment_term_id:
            values['payment_term_id'] = quotation.payment_term_id.id
        if quotation.validity_date:
            values['validity_date'] = quotation.validity_date
        return values

    @api.model
    def _create_sale_order_lines(self, quotation, order):
        SaleLine = self.env['sale.order.line']
        for line in quotation.line_ids.filtered(lambda item: not item.display_type):
            values = self._prepare_sale_order_line_values(line, order)
            SaleLine.create(values)

    @api.model
    def _prepare_sale_order_line_values(self, line, order):
        values = {
            'order_id': order.id,
            'name': line.name,
            'product_uom_qty': line.product_uom_qty,
            'price_unit': line.price_unit,
            'discount': line.discount,
            'tax_id': [(6, 0, line.tax_id.ids)],
        }
        if line.product_id:
            values.update({
                'product_id': line.product_id.id,
                'product_uom': line.product_uom_id.id or line.product_id.uom_id.id,
            })
        elif line.product_uom_id:
            values['product_uom'] = line.product_uom_id.id
        SaleLine = self.env['sale.order.line']
        if 'price_locked' in SaleLine._fields:
            values['price_locked'] = True
        return values

    @api.model
    def _get_product_price(self, quotation, product, quantity):
        pricelist = quotation.pricelist_id
        partner = quotation.partner_id or self.env.user.partner_id
        if pricelist:
            try:
                return pricelist._get_product_price(product, quantity, partner)
            except Exception as exc:
                self._vq_log(
                    'PRICE FALLBACK',
                    'Pricelist price failed',
                    level='warning',
                    quotation_id=quotation.id,
                    product_id=product.id,
                    error=str(exc),
                )
        return product.lst_price

    @api.model
    def _get_product_taxes(self, product):
        return product.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == self.env.company
        )

    @api.model
    def _prepare_product_line_extension_values(self, quotation, product, quantity):
        return {}

    @api.model
    def _prepare_manual_line_extension_values(self, quotation, values):
        return {}

    @api.model
    def _as_float(self, value, fallback=0.0):
        try:
            return float(value if value is not None else fallback)
        except (TypeError, ValueError):
            return float(fallback or 0.0)
