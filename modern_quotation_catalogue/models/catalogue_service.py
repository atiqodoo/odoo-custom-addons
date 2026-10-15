# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class ModernQuotationCatalogueService(models.AbstractModel):
    _name = 'modern.quotation.catalogue.service'
    _description = 'Modern Quotation Catalogue Service'

    LOG_HEAD = 'MODERN QUOTATION CATALOGUE'
    DEFAULT_DRAFT_PARTNER_PARAM = 'modern_quotation_catalogue.default_draft_partner_id'
    COST_SORT_DIRECTIONS = {
        'cost_incl_vat_asc': 'asc',
        'cost_incl_vat_desc': 'desc',
    }
    VARIANT_COMPARISON_LIMIT = 80

    def _log_head(self, operation, message='', level='info', **payload):
        parts = ['=' * 18, self.LOG_HEAD, operation]
        if message:
            parts.append(message)
        parts.append('=' * 18)
        log_message = ' | '.join(parts)
        if payload:
            log_message = '%s | %s' % (log_message, payload)
        getattr(_logger, level)(log_message)

    def _has_model(self, model_name):
        return bool(self.env['ir.model'].sudo().search_count([('model', '=', model_name)]))

    def _has_field(self, model_name, field_name):
        return field_name in self.env[model_name]._fields

    def _can_view_cost(self):
        return self.env.user.has_group('base.group_user')

    @api.model
    def get_bootstrap(self, order_id=False):
        self._log_head('BOOTSTRAP START', order_id=order_id, user_id=self.env.uid)
        order = self.env['sale.order'].browse(order_id).exists() if order_id else self.env['sale.order']
        partners = self.env['res.partner'].search([('customer_rank', '>', 0)], limit=40, order='name')
        default_draft_partner = self._get_default_draft_partner()
        if default_draft_partner and default_draft_partner not in partners:
            partners |= default_draft_partner
        if order and order.partner_id and order.partner_id not in partners:
            partners |= order.partner_id
        pricelists = self.env['product.pricelist'].search([], limit=80, order='name')
        warehouses = self.env['stock.warehouse'].search([], order='name')
        all_categories = self.env['product.category'].search([], order='complete_name')
        category_sales = self._get_category_sold_qty_rollup(
            all_categories,
            self._get_filter_sold_qty_by_template_field('categ_id'),
        )
        uom_sales = self._get_filter_sold_qty_by_template_field('uom_id')
        category_groups = self.env['modern.quotation.category.group'].search([('active', '=', True)])
        categories = self._prepare_ranked_category_filters(all_categories, category_groups, category_sales, limit=200)
        uoms = self._sort_filter_records_by_sold_qty(
            self.env['uom.uom'].search([], order='category_id, name'),
            uom_sales,
            limit=200,
        )
        attributes = self.env['product.attribute'].search([], limit=80, order='name')

        data = {
            'order': self._format_order(order) if order else False,
            'partners': self._name_list(partners),
            'pricelists': self._name_list(pricelists),
            'warehouses': self._name_list(warehouses),
            'categories': categories,
            'uoms': [{
                'id': u.id,
                'name': u.display_name,
                'category_id': u.category_id.id,
                'qty_sold': self._as_float(uom_sales.get(u.id)),
            } for u in uoms],
            'attributes': [{
                'id': attr.id,
                'name': attr.name,
                'values': self._name_list(attr.value_ids),
            } for attr in attributes],
            'default_draft_partner': {
                'id': default_draft_partner.id,
                'name': default_draft_partner.display_name,
            } if default_draft_partner else False,
            'can_view_cost': self._can_view_cost(),
            'has_colour_master': self._has_model('colour.code'),
            'has_tinting': self._has_field('sale.order.line', 'is_tinted_product_line'),
        }
        self._log_head('BOOTSTRAP DONE', counts={
            'partners': len(partners),
            'default_draft_partner_id': default_draft_partner.id if default_draft_partner else False,
            'categories': len(categories),
            'category_groups': len(category_groups),
            'uoms': len(uoms),
            'attributes': len(attributes),
        }, ranked_filters={
            'categories': [(category['value'], category['qty_sold']) for category in categories[:5]],
            'uoms': [(uom.id, self._as_float(uom_sales.get(uom.id))) for uom in uoms[:5]],
        })
        return data

    @api.model
    def search_partners(self, term=''):
        domain = []
        if term:
            domain = ['|', '|', ('name', 'ilike', term), ('phone', 'ilike', term), ('email', 'ilike', term)]
        partners = self.env['res.partner'].search(domain, limit=40, order='customer_rank desc, name')
        return self._name_list(partners)

    @api.model
    def quick_create_customer(self, name):
        self._log_head('QUICK CREATE CUSTOMER START', name=name, user_id=self.env.uid)
        if not name:
            raise UserError(_('Customer name is required.'))
        partner = self.env['res.partner'].create({
            'name': name,
            'customer_rank': 1,
        })
        self._log_head('QUICK CREATE CUSTOMER DONE', partner_id=partner.id, name=partner.display_name)
        return {'id': partner.id, 'display_name': partner.display_name}

    @api.model
    def create_or_load_quotation(self, values):
        values = values or {}
        order_id = values.get('order_id')
        self._log_head('CREATE OR LOAD START', order_id=order_id, values=values)
        if order_id:
            order = self.env['sale.order'].browse(order_id).exists()
            if not order:
                raise UserError(_('Quotation not found.'))
            self._log_head('CREATE OR LOAD EXISTING DONE', order_id=order.id, name=order.name)
            return self._format_order(order)

        partner_id = values.get('partner_id')
        if not partner_id:
            default_partner = self._get_default_draft_partner()
            if not default_partner:
                raise UserError(_(
                    'Configure a default draft quotation customer in Modern Quotation Settings, '
                    'or select a customer before creating the quotation.'
                ))
            partner_id = default_partner.id
            self._log_head('CREATE QUOTATION USING DEFAULT CUSTOMER', partner_id=partner_id)

        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise UserError(_('Selected customer was not found.'))

        order_vals = {
            'partner_id': partner.id,
        }
        if values.get('pricelist_id'):
            order_vals['pricelist_id'] = values['pricelist_id']
        if values.get('warehouse_id'):
            order_vals['warehouse_id'] = values['warehouse_id']

        order = self.env['sale.order'].create(order_vals)
        order.message_post(body=_('Quotation created from Modern Quotation Catalogue workspace.'))
        self._log_head('CREATE QUOTATION DONE', order_id=order.id, name=order.name, partner_id=partner.id)
        return self._format_order(order)

    def _get_default_draft_partner(self):
        partner_id = self.env['ir.config_parameter'].sudo().get_param(self.DEFAULT_DRAFT_PARTNER_PARAM)
        if not partner_id:
            return self.env['res.partner']
        try:
            partner = self.env['res.partner'].browse(int(partner_id)).exists()
        except (TypeError, ValueError):
            self._log_head('DEFAULT CUSTOMER CONFIG INVALID', level='warning', partner_id=partner_id)
            return self.env['res.partner']
        return partner

    @api.model
    def search_catalogue(self, filters=None):
        filters = filters or {}
        self._log_head('CATALOGUE SEARCH START', filters=filters, user_id=self.env.uid)
        limit = min(int(filters.get('limit') or 60), 120)
        offset = max(int(filters.get('offset') or 0), 0)
        warehouse_id = filters.get('warehouse_id')
        domain = self._get_catalogue_domain(filters)
        ctx = self._get_stock_context(warehouse_id)

        Product = self.env['product.product'].with_context(ctx)
        product_ids = Product.search(domain, order='id').ids
        total = len(product_ids)
        sold_qty_by_product = self._get_sold_qty_by_product(product_ids)
        ranked_product_ids, ranked_by = self._rank_catalogue_product_ids(product_ids, filters, sold_qty_by_product)
        page_product_ids = ranked_product_ids[offset:offset + limit]
        products_by_id = {product.id: product for product in Product.browse(page_product_ids).exists()}
        rows = [
            self._format_product(products_by_id[product_id], filters, sold_qty_by_product.get(product_id, 0.0))
            for product_id in page_product_ids
            if product_id in products_by_id
        ]
        self._log_head(
            'CATALOGUE SEARCH DONE',
            total=total,
            returned=len(rows),
            offset=offset,
            limit=limit,
            ranked_by=ranked_by,
            top=[(row['id'], row['qty_sold'], row.get('cost_incl_vat')) for row in rows[:5]],
        )
        return {
            'products': rows,
            'total': total,
            'offset': offset,
            'limit': limit,
        }

    @api.model
    def add_product_to_quotation(self, order_id, product_id, quantity=1.0):
        self._log_head('ADD PRODUCT START', order_id=order_id, product_id=product_id, quantity=quantity)
        order = self.env['sale.order'].browse(order_id).exists()
        product = self.env['product.product'].browse(product_id).exists()
        if not order or not product:
            raise UserError(_('Quotation or product was not found.'))
        if order.state not in ('draft', 'sent'):
            raise UserError(_('Products can only be added to draft quotations.'))

        quantity = float(quantity or 1.0)
        line = order.order_line.filtered(
            lambda item: not item.display_type
            and item.product_id == product
            and not getattr(item, 'is_tinted_product_line', False)
        )[:1]
        if line:
            line.write({'product_uom_qty': line.product_uom_qty + quantity})
            line._mqc_capture_profit_snapshot(force_cost=False)
            self._log_head('ADD PRODUCT MERGED', line_id=line.id, new_qty=line.product_uom_qty)
        else:
            vals = self._prepare_sale_line_values(order, product, quantity)
            line = self.env['sale.order.line'].create(vals)
            line._mqc_capture_profit_snapshot(force_cost=True)
            self._log_head('ADD PRODUCT LINE CREATED', line_id=line.id, vals=vals)
        return self._format_order(order)

    @api.model
    def replace_line_with_alternate(self, line_id, product_id, quantity, price_incl_vat):
        self._log_head('REPLACE WITH ALTERNATE START', line_id=line_id, product_id=product_id, quantity=quantity, price_incl_vat=price_incl_vat)
        line = self.env['sale.order.line'].browse(line_id).exists()
        product = self.env['product.product'].browse(product_id).exists()
        if not line or not product:
            raise UserError(_('Quotation line or alternate variant was not found.'))
        order = line.order_id
        self._ensure_order_can_accept_alternate(order)
        quantity = float(quantity or 1.0)
        price_unit = self._prepare_alternate_price_unit(product, quantity, price_incl_vat, order)
        vals = {
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'price_unit': price_unit,
        }
        if self._has_field('sale.order.line', 'price_locked'):
            vals['price_locked'] = True
        line.write(vals)
        line._mqc_capture_profit_snapshot(force_cost=True)
        self._log_head('REPLACE WITH ALTERNATE DONE', order_id=order.id, line_id=line.id, product_id=product.id, quantity=quantity, price_unit=price_unit)
        return self._format_order(order)

    @api.model
    def add_alternate_to_quotation(self, order_id, product_id, quantity, price_incl_vat):
        self._log_head('ADD ALTERNATE START', order_id=order_id, product_id=product_id, quantity=quantity, price_incl_vat=price_incl_vat)
        order = self.env['sale.order'].browse(order_id).exists()
        product = self.env['product.product'].browse(product_id).exists()
        if not order or not product:
            raise UserError(_('Quotation or alternate variant was not found.'))
        self._ensure_order_can_accept_alternate(order)
        quantity = float(quantity or 1.0)
        price_unit = self._prepare_alternate_price_unit(product, quantity, price_incl_vat, order)
        vals = self._prepare_sale_line_values(order, product, quantity)
        vals['price_unit'] = price_unit
        if self._has_field('sale.order.line', 'price_locked'):
            vals['price_locked'] = True
        line = self.env['sale.order.line'].create(vals)
        line._mqc_capture_profit_snapshot(force_cost=True)
        self._log_head('ADD ALTERNATE DONE', order_id=order.id, line_id=line.id, product_id=product.id, price_unit=price_unit)
        return self._format_order(order)

    def _ensure_order_can_accept_alternate(self, order):
        if order.state not in ('draft', 'sent'):
            raise UserError(_('Alternates can only be applied to draft quotations.'))

    def _prepare_alternate_price_unit(self, product, quantity, price_incl_vat, order):
        quantity = float(quantity or 1.0)
        price_incl_vat = self._as_float(price_incl_vat)
        cost_excl = self._as_float(self._get_product_cost_in_order_currency(product, {
            'pricelist_id': order.pricelist_id.id,
        }))
        cost_incl = self._as_float(self._get_cost_including_tax(product, cost_excl), cost_excl)
        self._raise_if_alternate_below_cost(product, price_incl_vat, cost_incl)
        return price_incl_vat

    def _raise_if_alternate_below_cost(self, product, price_incl_vat, cost_incl_vat):
        precision = self.env.company.currency_id.rounding or 0.01
        if float_compare(price_incl_vat, cost_incl_vat, precision_rounding=precision) < 0:
            raise UserError(_(
                "You cannot apply this alternate because the price is below cost price "
                "(VAT inclusive): %s: selling %.2f < cost %.2f"
            ) % (product.display_name, round(price_incl_vat, 2), round(cost_incl_vat, 2)))

    def _get_product_sale_price_excl_vat(self, product, price_incl_vat, quantity, order):
        taxes = product.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == order.company_id)
        if not taxes:
            return price_incl_vat
        try:
            tax_result = taxes.compute_all(
                price_incl_vat,
                currency=order.currency_id,
                quantity=quantity,
                product=product,
                partner=order.partner_shipping_id or order.partner_id,
                handle_price_include=True,
            )
            total_excluded = self._as_float(tax_result.get('total_excluded'), price_incl_vat * quantity)
            return total_excluded / quantity if quantity else price_incl_vat
        except Exception as exc:
            self._log_head('ALTERNATE PRICE TAX FALLBACK', 'tax reverse computation failed', level='warning', product_id=product.id, error=str(exc))
            return price_incl_vat

    @api.model
    def update_line_quantity(self, line_id, quantity):
        self._log_head('UPDATE LINE QTY START', line_id=line_id, quantity=quantity)
        line = self.env['sale.order.line'].browse(line_id).exists()
        if not line:
            raise UserError(_('Quotation line not found.'))
        line.write({'product_uom_qty': float(quantity or 0.0)})
        line._mqc_capture_profit_snapshot(force_cost=False)
        self._log_head('UPDATE LINE QTY DONE', line_id=line.id, order_id=line.order_id.id)
        return self._format_order(line.order_id)

    @api.model
    def update_line_price(self, line_id, price_unit):
        self._log_head('UPDATE LINE PRICE START', line_id=line_id, price_unit=price_unit)
        line = self.env['sale.order.line'].browse(line_id).exists()
        if not line:
            raise UserError(_('Quotation line not found.'))
        vals = {'price_unit': float(price_unit or 0.0)}
        if self._has_field('sale.order.line', 'price_locked'):
            vals['price_locked'] = True
        line.write(vals)
        line._mqc_capture_profit_snapshot(force_cost=False)
        self._log_head('UPDATE LINE PRICE DONE', line_id=line.id, order_id=line.order_id.id, price_unit=line.price_unit)
        return self._format_order(line.order_id)

    @api.model
    def remove_line(self, line_id):
        self._log_head('REMOVE LINE START', line_id=line_id)
        line = self.env['sale.order.line'].browse(line_id).exists()
        if not line:
            raise UserError(_('Quotation line not found.'))
        order = line.order_id
        line.unlink()
        self._log_head('REMOVE LINE DONE', order_id=order.id)
        return self._format_order(order)

    @api.model
    def confirm_quotation(self, order_id):
        self._log_head('CONFIRM START', order_id=order_id)
        order = self.env['sale.order'].browse(order_id).exists()
        if not order:
            raise UserError(_('Quotation not found.'))
        order.action_confirm()
        self._log_head('CONFIRM DONE', order_id=order.id, state=order.state)
        return self._format_order(order)

    @api.model
    def open_quotation_action(self, order_id):
        order = self.env['sale.order'].browse(order_id).exists()
        if not order:
            raise UserError(_('Quotation not found.'))
        self._raise_if_order_has_below_cost_lines(order, operation=_('open'))
        return {
            'type': 'ir.actions.act_window',
            'name': order.name,
            'res_model': 'sale.order',
            'res_id': order.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def compare_similar_variants(
        self,
        product_id,
        order_id=False,
        line_id=False,
        quantity=1.0,
        sort_by='cost_incl_vat_asc',
        filters=None,
        comparison_filters=None,
    ):
        filters = filters or {}
        comparison_filters = comparison_filters or {}
        self._log_head(
            'VARIANT COMPARISON START',
            product_id=product_id,
            order_id=order_id,
            line_id=line_id,
            quantity=quantity,
            sort_by=sort_by,
            filters=filters,
            comparison_filters=comparison_filters,
        )
        order = self.env['sale.order'].browse(order_id).exists() if order_id else self.env['sale.order']
        target_line = self._get_comparison_target_line(order, self.env['product.product'].browse(product_id).exists(), line_id)
        selected_product = target_line.product_id if target_line else self.env['product.product'].browse(product_id).exists()
        if not selected_product:
            raise UserError(_('Selected variant was not found.'))

        context = self._get_variant_comparison_context(order, target_line, quantity, filters)
        selected_colour_group = self._get_product_colour_attribute_group(selected_product)
        comparison_uom = self._get_comparison_uom(selected_product, comparison_filters)
        all_colour_groups = comparison_filters.get('colour_attribute_group_id') == 'all'
        colour_attribute_term = (comparison_filters.get('colour_attribute_filter') or '').strip()
        colour_group = self._get_comparison_colour_attribute_group(selected_colour_group, comparison_filters)
        category_scope = self._get_variant_comparison_category_scope(selected_product)
        category_domain = self._get_category_filter_domain(comparison_filters)
        Product = self.env['product.product'].with_context(self._get_stock_context(filters.get('warehouse_id')))
        compared_products = Product.search(
            self._get_variant_similarity_domain(
                selected_product,
                category_scope,
                category_domain,
                comparison_uom,
                colour_group,
                all_colour_groups=all_colour_groups,
                colour_attribute_term=colour_attribute_term,
            ),
            limit=self.VARIANT_COMPARISON_LIMIT,
        )
        rows = [
            self._prepare_variant_comparison_row(product, context)
            for product in compared_products
        ]
        rows = self._sort_variant_comparison_rows(rows, sort_by)
        payload = {
            'selected_product': self._prepare_selected_comparison_product(selected_product),
            'basis': {
                'category_id': selected_product.categ_id.id,
                'category': selected_product.categ_id.complete_name or selected_product.categ_id.name or '',
                'category_scope_id': category_scope.id,
                'category_scope': category_scope.complete_name or category_scope.name or '',
                'category_filter': comparison_filters.get('category_filter') or comparison_filters.get('category_id') or '',
                'uom_id': comparison_uom.id,
                'uom': comparison_uom.display_name,
                'quantity': context['quantity'],
                'mode': 'replace_line' if target_line else 'add_to_order',
                'line_id': target_line.id if target_line else False,
                'colour_attribute_group_id': 'all' if all_colour_groups else (colour_group.id if colour_group else False),
                'colour_attribute_group': _('All groups') if all_colour_groups else (colour_group.display_name if colour_group else ''),
                'base_total': context['base_total'],
                'base_profit': context['base_profit'],
                'current_quote_total': context['current_quote_total'],
                'other_line_count': context['other_line_count'],
                'currency': context['currency'],
            },
            'filter_options': self._get_variant_comparison_filter_options(selected_product),
            'rows': rows,
        }
        self._log_head(
            'VARIANT COMPARISON DONE',
            selected_product_id=selected_product.id,
            line_id=target_line.id if target_line else False,
            category_id=selected_product.categ_id.id,
            category_scope_id=category_scope.id,
            category_filter=comparison_filters.get('category_filter') or comparison_filters.get('category_id') or '',
            uom_id=comparison_uom.id,
            colour_attribute_group_id=colour_group.id if colour_group else False,
            row_count=len(rows),
            mode=payload['basis']['mode'],
            quantity=payload['basis']['quantity'],
            top=[(row['id'], row['cost_incl_vat'], row['quotation_total_if_used']) for row in rows[:5]],
        )
        return payload

    def _get_comparison_target_line(self, order, selected_product, line_id=False):
        if not order:
            return self.env['sale.order.line']
        if line_id:
            line = order.order_line.filtered(lambda item: item.id == int(line_id))[:1]
            if line:
                return line
        return order.order_line.filtered(
            lambda item: not item.display_type and item.product_id == selected_product
        )[:1]

    def _get_variant_comparison_context(self, order, target_line, quantity, filters):
        quantity = target_line.product_uom_qty if target_line else max(self._as_float(quantity, 1.0), 0.01)
        order_total = self._as_float(order.amount_total) if order else 0.0
        order_profit = self._get_order_profit_total_incl_vat(order) if order else 0.0
        line_total = self._as_float(target_line.price_total) if target_line else 0.0
        line_profit = self._as_float(getattr(target_line, 'mqc_profit_total_incl_vat_snapshot', 0.0)) if target_line else 0.0
        currency = order.currency_id.symbol or order.currency_id.name if order else self.env.company.currency_id.symbol or self.env.company.currency_id.name
        return {
            'filters': filters,
            'quantity': quantity,
            'current_quote_total': order_total,
            'base_total': order_total - line_total,
            'base_profit': order_profit - line_profit,
            'other_line_count': len(order.order_line.filtered(lambda item: not item.display_type and item.product_id)) - (1 if target_line else 0) if order else 0,
            'currency': currency,
        }

    def _get_order_profit_total_incl_vat(self, order):
        if hasattr(order, '_mqc_ensure_profit_snapshots'):
            order._mqc_ensure_profit_snapshots()
        return sum(
            self._as_float(getattr(line, 'mqc_profit_total_incl_vat_snapshot', 0.0))
            for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id)
        )

    def _get_comparison_uom(self, product, comparison_filters):
        uom_id = comparison_filters.get('uom_id')
        if uom_id:
            uom = self.env['uom.uom'].browse(int(uom_id)).exists()
            if uom:
                return uom
        return product.uom_id

    def _get_comparison_colour_attribute_group(self, default_group, comparison_filters):
        term = (comparison_filters.get('colour_attribute_filter') or '').strip()
        if term:
            colour_ids, attribute_value_ids = self._get_colour_attribute_filter_links(term)
            groups = self.env['modern.quotation.colour.attribute.group']
            if colour_ids:
                groups |= self.env['modern.quotation.colour.attribute.group'].search([
                    ('active', '=', True),
                    ('colour_code_ids', 'in', colour_ids),
                ])
            if attribute_value_ids:
                groups |= self.env['modern.quotation.colour.attribute.group'].search([
                    ('active', '=', True),
                    ('attribute_value_ids', 'in', attribute_value_ids),
                ])
            if groups:
                return groups[:1]
        group_id = comparison_filters.get('colour_attribute_group_id')
        if group_id == 'all':
            return self.env['modern.quotation.colour.attribute.group']
        if group_id:
            group = self.env['modern.quotation.colour.attribute.group'].browse(int(group_id)).exists()
            if group:
                return group
        return default_group

    def _get_variant_comparison_category_scope(self, product):
        category = product.categ_id
        if not category:
            return category
        if category.child_id:
            return category
        return category.parent_id or category

    def _get_variant_similarity_domain(self, product, category_scope, category_domain, uom, colour_group=False, all_colour_groups=False, colour_attribute_term=''):
        domain = [
            ('sale_ok', '=', True),
            ('active', '=', True),
            ('uom_id', '=', uom.id),
        ]
        domain += category_domain or [('categ_id', 'child_of', category_scope.id)]
        if colour_attribute_term:
            return domain + self._get_variant_filter_domain(colour_attribute_term)
        if all_colour_groups:
            return domain
        if not colour_group:
            self._log_head(
                'VARIANT COMPARISON NO COLOUR GROUP',
                product_id=product.id,
                product_name=product.display_name,
                category_id=product.categ_id.id,
                category_scope_id=category_scope.id,
                uom_id=uom.id,
                level='warning',
            )
            return domain

        group_domain = []
        if self._has_field('product.template', 'colour_code_id') and colour_group.colour_code_ids:
            group_domain.append(('product_tmpl_id.colour_code_id', 'in', colour_group.colour_code_ids.ids))
        if colour_group.attribute_value_ids:
            group_domain.append((
                'product_template_attribute_value_ids.product_attribute_value_id',
                'in',
                colour_group.attribute_value_ids.ids,
            ))
        if not group_domain:
            return [('id', '=', 0)]
        if len(group_domain) == 1:
            return domain + group_domain
        return domain + ['|'] * (len(group_domain) - 1) + group_domain

    def _get_variant_comparison_filter_options(self, selected_product):
        category_scope = self._get_variant_comparison_category_scope(selected_product)
        category_products = self.env['product.product'].search([
            ('sale_ok', '=', True),
            ('active', '=', True),
            ('categ_id', 'child_of', category_scope.id),
        ])
        uoms = category_products.mapped('uom_id').sorted(lambda uom: (uom.display_name or '', uom.id))
        groups = self.env['modern.quotation.colour.attribute.group'].search([('active', '=', True)], order='sequence, name, id')
        return {
            'uoms': [{'id': uom.id, 'name': uom.display_name} for uom in uoms],
            'colour_attribute_groups': [{'id': group.id, 'name': group.display_name} for group in groups],
        }

    def _get_product_colour_attribute_group(self, product):
        if not self._has_model('modern.quotation.colour.attribute.group'):
            return self.env['modern.quotation.colour.attribute.group']

        search_terms = []
        if self._has_field('product.template', 'colour_code_id') and product.product_tmpl_id.colour_code_id:
            search_terms.append(('colour_code_ids', 'in', [product.product_tmpl_id.colour_code_id.id]))

        attribute_value_ids = product.product_template_attribute_value_ids.mapped('product_attribute_value_id').ids
        if attribute_value_ids:
            search_terms.append(('attribute_value_ids', 'in', attribute_value_ids))

        if not search_terms:
            return self.env['modern.quotation.colour.attribute.group']
        domain = [('active', '=', True)]
        if len(search_terms) == 1:
            domain += search_terms
        else:
            domain += ['|'] * (len(search_terms) - 1) + search_terms
        return self.env['modern.quotation.colour.attribute.group'].search(domain, limit=1)

    def _prepare_selected_comparison_product(self, product):
        return {
            'id': product.id,
            'name': product.display_name,
            'category': product.categ_id.complete_name or product.categ_id.name or '',
            'uom': product.uom_id.display_name,
        }

    def _prepare_variant_comparison_row(self, product, context):
        filters = context['filters']
        quantity = context['quantity']
        sale_price_excl = self._as_float(self._get_sale_price(product, filters))
        sale_price_incl = self._as_float(self._get_product_sale_price_incl_vat(product, sale_price_excl))
        cost_excl = self._as_float(self._get_product_cost_in_order_currency(product, filters))
        cost_incl = self._as_float(self._get_cost_including_tax(product, cost_excl), cost_excl)
        line_total = sale_price_incl * quantity
        line_profit = line_total - (cost_incl * quantity)
        return {
            'id': product.id,
            'name': product.display_name,
            'default_code': product.default_code or '',
            'attributes': ', '.join(product.product_template_attribute_value_ids.mapped('display_name')),
            'category': product.categ_id.complete_name or product.categ_id.name or '',
            'uom': product.uom_id.display_name,
            'quantity': quantity,
            'sale_price_incl_vat': sale_price_incl,
            'cost_incl_vat': cost_incl,
            'line_total_if_used': line_total,
            'line_profit_if_used': line_profit,
            'current_quote_total': context['current_quote_total'],
            'quotation_total_if_used': context['base_total'] + line_total,
            'quotation_profit_if_used': context['base_profit'] + line_profit,
            'temporary_quote_lines': self._prepare_temporary_quote_lines(product, line_total, context),
            'currency': context['currency'],
        }

    def _prepare_temporary_quote_lines(self, replacement_product, replacement_total, context):
        return [{
            'role': 'replacement',
            'name': replacement_product.display_name,
            'quantity': context['quantity'],
            'total': replacement_total,
        }, {
            'role': 'other_lines',
            'name': _('Other selected quotation variants'),
            'quantity': context['other_line_count'],
            'total': context['base_total'],
        }]

    def _sort_variant_comparison_rows(self, rows, sort_by):
        direction = self.COST_SORT_DIRECTIONS.get(sort_by) or 'asc'
        return sorted(
            rows,
            key=lambda row: (
                row['cost_incl_vat'] if direction == 'asc' else -row['cost_incl_vat'],
                row['name'],
                row['id'],
            ),
        )

    def _get_product_sale_price_incl_vat(self, product, sale_price_excl):
        taxes = product.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == self.env.company)
        if not taxes:
            return sale_price_excl
        try:
            tax_result = taxes.compute_all(
                sale_price_excl,
                currency=self.env.company.currency_id,
                quantity=1.0,
                product=product,
                partner=False,
            )
            return self._as_float(tax_result.get('total_included'), sale_price_excl)
        except Exception as exc:
            self._log_head('COMPARISON PRICE TAX FALLBACK', 'tax computation failed', level='warning', product_id=product.id, error=str(exc))
            return sale_price_excl

    def _raise_if_order_has_below_cost_lines(self, order, operation):
        offenders = self._get_order_below_cost_lines(order)
        if not offenders:
            return

        detail_lines = [
            "%s: selling %.2f < cost %.2f"
            % (item['product_name'], item['price_incl'], item['cost_incl'])
            for item in offenders
        ]
        raise UserError(_(
            "You cannot %(operation)s this sales order because these products "
            "are below cost price (VAT inclusive):\n%(lines)s"
        ) % {
            'operation': operation,
            'lines': "\n".join(detail_lines),
        })

    def _get_order_below_cost_lines(self, order):
        order.ensure_one()
        if hasattr(order, '_get_below_cost_lines_vat_incl'):
            return order._get_below_cost_lines_vat_incl()
        return self._get_order_below_cost_lines_from_mqc_snapshots(order)

    def _get_order_below_cost_lines_from_mqc_snapshots(self, order):
        if hasattr(order, '_mqc_ensure_profit_snapshots'):
            order._mqc_ensure_profit_snapshots()

        offenders = []
        precision = order.currency_id.rounding or 0.01
        lines = order.order_line.filtered(lambda line: not line.display_type and line.product_id and line.product_uom_qty > 0)
        for line in lines:
            cost_incl = self._as_float(getattr(line, 'mqc_profit_cost_unit_incl_vat_snapshot', 0.0))
            if not cost_incl:
                continue

            quantity = line.product_uom_qty or 0.0
            price_incl = (line.price_total / quantity) if quantity else line.price_unit
            if float_compare(price_incl, cost_incl, precision_rounding=precision) < 0:
                offenders.append({
                    'product_name': line.product_id.display_name,
                    'price_incl': round(price_incl, 2),
                    'cost_incl': round(cost_incl, 2),
                })
        return offenders

    def _get_catalogue_domain(self, filters):
        domain = [('sale_ok', '=', True), ('active', '=', True)]
        if filters.get('search'):
            term = filters['search']
            domain += ['|', '|', ('display_name', 'ilike', term), ('default_code', 'ilike', term), ('barcode', 'ilike', term)]
        category_domain = self._get_category_filter_domain(filters)
        if category_domain:
            domain += category_domain
        if filters.get('uom_id'):
            domain.append(('uom_id', '=', int(filters['uom_id'])))
        if filters.get('attribute_value_ids'):
            domain.append(('product_template_attribute_value_ids.product_attribute_value_id', 'in', filters['attribute_value_ids']))
        variant_term = (filters.get('variant_filter') or filters.get('colour_code') or '').strip()
        if variant_term:
            domain += self._get_variant_filter_domain(variant_term)
        if filters.get('fandeck_id') and self._has_field('product.template', 'fandeck_id'):
            domain.append(('product_tmpl_id.fandeck_id', '=', int(filters['fandeck_id'])))
        return domain

    def _get_category_filter_domain(self, filters):
        category_filter = filters.get('category_filter') or filters.get('category_id')
        if not category_filter:
            return []

        if isinstance(category_filter, str) and ':' in category_filter:
            filter_type, filter_id = category_filter.split(':', 1)
            filter_id = int(filter_id)
        else:
            filter_type, filter_id = 'category', int(category_filter)

        if filter_type == 'group':
            group = self.env['modern.quotation.category.group'].browse(filter_id).exists()
            child_ids = group.child_category_ids.ids if group else []
            if not child_ids:
                return [('id', '=', 0)]
            return [('categ_id', 'child_of', child_ids)]

        return [('categ_id', 'child_of', filter_id)]

    def _get_variant_filter_domain(self, term):
        search_fields = [
            ('product_template_attribute_value_ids.name', 'ilike', term),
            ('product_template_attribute_value_ids.product_attribute_value_id.name', 'ilike', term),
        ]
        mapped_colour_ids, mapped_attribute_value_ids = self._get_colour_attribute_filter_links(term)
        if mapped_attribute_value_ids:
            search_fields.append(
                ('product_template_attribute_value_ids.product_attribute_value_id', 'in', mapped_attribute_value_ids)
            )
        if self._has_field('product.template', 'colour_code_id'):
            search_fields += [
                ('product_tmpl_id.colour_code_id.code', 'ilike', term),
                ('product_tmpl_id.colour_code_id.name', 'ilike', term),
                ('product_tmpl_id.colour_name', 'ilike', term),
            ]
            if mapped_colour_ids:
                search_fields.append(('product_tmpl_id.colour_code_id', 'in', mapped_colour_ids))
        if len(search_fields) == 1:
            return search_fields
        return ['|'] * (len(search_fields) - 1) + search_fields

    def _get_colour_attribute_filter_links(self, term):
        if not term or not self._has_model('modern.quotation.colour.attribute.group'):
            return [], []

        domain = [
            ('active', '=', True),
            '|', '|', '|',
            ('name', 'ilike', term),
            ('colour_code_ids.code', 'ilike', term),
            ('colour_code_ids.name', 'ilike', term),
            ('attribute_value_ids.name', 'ilike', term),
        ]
        groups = self.env['modern.quotation.colour.attribute.group'].search(domain)
        colour_ids = groups.mapped('colour_code_ids').ids
        attribute_value_ids = groups.mapped('attribute_value_ids').ids
        if groups:
            self._log_head(
                'COLOUR ATTRIBUTE FILTER EXPANDED',
                term=term,
                group_ids=groups.ids,
                colour_ids=colour_ids,
                attribute_value_ids=attribute_value_ids,
            )
        return colour_ids, attribute_value_ids

    def _get_stock_context(self, warehouse_id=False):
        ctx = {}
        if warehouse_id:
            warehouse = self.env['stock.warehouse'].browse(int(warehouse_id)).exists()
            if warehouse:
                ctx['warehouse'] = warehouse.id
        return ctx

    def _prepare_sale_line_values(self, order, product, quantity):
        vals = {
            'order_id': order.id,
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
        }
        if self._has_field('sale.order.line', 'price_locked'):
            vals['price_locked'] = False
        return vals

    def _format_product(self, product, filters, qty_sold=0.0):
        tmpl = product.product_tmpl_id
        qty_product = product.with_context(self._get_stock_context(filters.get('warehouse_id')))
        sale_price = self._as_float(self._get_sale_price(product, filters))
        values = {
            'id': product.id,
            'template_id': tmpl.id,
            'name': product.display_name,
            'default_code': product.default_code or '',
            'barcode': product.barcode or '',
            'category': product.categ_id.complete_name or product.categ_id.name or '',
            'uom': product.uom_id.display_name,
            'qty_available': qty_product.qty_available,
            'virtual_available': qty_product.virtual_available,
            'qty_sold': self._as_float(qty_sold),
            'sale_price': sale_price,
            'currency': self.env.company.currency_id.symbol or self.env.company.currency_id.name,
            'attributes': ', '.join(product.product_template_attribute_value_ids.mapped('display_name')),
            'image_url': '/web/image/product.product/%s/image_128' % product.id,
            'warning_flags': self._get_product_warning_flags(qty_product),
        }
        if self._can_view_cost():
            cost_excl = self._as_float(self._get_product_cost_in_order_currency(product, filters))
            cost_incl = self._as_float(self._get_cost_including_tax(product, cost_excl), cost_excl)
            values.update({
                'cost_excl_vat': cost_excl,
                'cost_incl_vat': cost_incl,
                'margin': sale_price - cost_incl,
            })
        if self._has_field('product.template', 'colour_code_id'):
            colour = tmpl.colour_code_id
            values.update({
                'colour_code_id': colour.id if colour else False,
                'colour_code': getattr(colour, 'code', '') if colour else '',
                'colour_name': colour.name if colour else (getattr(tmpl, 'colour_name', '') or ''),
            })
        if self._has_field('product.template', 'fandeck_id'):
            values['fandeck'] = tmpl.fandeck_id.name if tmpl.fandeck_id else ''
            values['fandeck_id'] = tmpl.fandeck_id.id if tmpl.fandeck_id else False
        return values

    def _get_sold_qty_by_product(self, product_ids):
        qty_by_product = {product_id: 0.0 for product_id in product_ids}
        if not product_ids:
            return qty_by_product

        sale_groups = self.env['sale.order.line'].sudo().read_group(
            [
                ('product_id', 'in', product_ids),
                ('state', 'in', ['sale', 'done']),
                ('display_type', '=', False),
            ],
            ['product_uom_qty:sum'],
            ['product_id'],
            lazy=False,
        )
        for group in sale_groups:
            product = group.get('product_id')
            if product:
                qty_by_product[product[0]] = qty_by_product.get(product[0], 0.0) + self._as_float(group.get('product_uom_qty'))

        if self._has_model('pos.order.line'):
            pos_groups = self.env['pos.order.line'].sudo().read_group(
                [
                    ('product_id', 'in', product_ids),
                    ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                ],
                ['qty:sum'],
                ['product_id'],
                lazy=False,
            )
            for group in pos_groups:
                product = group.get('product_id')
                if product:
                    qty_by_product[product[0]] = qty_by_product.get(product[0], 0.0) + self._as_float(group.get('qty'))

        return qty_by_product

    def _rank_catalogue_product_ids(self, product_ids, filters, sold_qty_by_product):
        cost_sort_direction = self._get_cost_sort_direction(filters)
        if cost_sort_direction:
            return (
                self._sort_product_ids_by_cost_incl_vat(product_ids, filters, cost_sort_direction),
                'cost_incl_vat_%s' % cost_sort_direction,
            )
        return self._sort_product_ids_by_sold_qty(product_ids, sold_qty_by_product), 'sold_qty_all_channels'

    def _get_cost_sort_direction(self, filters):
        if not self._has_active_catalogue_filter(filters):
            return False
        return self.COST_SORT_DIRECTIONS.get(filters.get('sort_by'))

    def _has_active_catalogue_filter(self, filters):
        attribute_value_ids = filters.get('attribute_value_ids') or []
        return bool(
            (filters.get('search') or '').strip()
            or filters.get('category_filter')
            or filters.get('category_id')
            or filters.get('uom_id')
            or (filters.get('variant_filter') or '').strip()
            or (filters.get('colour_code') or '').strip()
            or attribute_value_ids
        )

    def _sort_product_ids_by_sold_qty(self, product_ids, sold_qty_by_product):
        products = self.env['product.product'].browse(product_ids).exists()
        product_sort_names = {
            product.id: ((product.default_code or ''), product.display_name or '', product.id)
            for product in products
        }
        return sorted(
            product_ids,
            key=lambda product_id: (
                -sold_qty_by_product.get(product_id, 0.0),
                product_sort_names.get(product_id, ('', '', product_id)),
            ),
        )

    def _sort_product_ids_by_cost_incl_vat(self, product_ids, filters, direction):
        products = self.env['product.product'].browse(product_ids).exists()
        sort_rows = []
        for product in products:
            cost_excl = self._as_float(self._get_product_cost_in_order_currency(product, filters))
            cost_incl = self._as_float(self._get_cost_including_tax(product, cost_excl), cost_excl)
            if direction == 'desc':
                cost_incl = -cost_incl
            sort_rows.append((
                cost_incl,
                product.default_code or '',
                product.display_name or '',
                product.id,
            ))
        return [product_id for *_sort_values, product_id in sorted(sort_rows)]

    def _prepare_ranked_category_filters(self, categories, category_groups, sold_qty_by_category, limit=False):
        grouped_category_ids = set(category_groups.mapped('child_category_ids').ids)
        rows = []
        ranked_blocks = []

        for group in category_groups:
            children = self._sort_filter_records_by_sold_qty(group.child_category_ids, sold_qty_by_category)
            group_sold_qty = sum(sold_qty_by_category.get(category.id, 0.0) for category in children)
            block = [{
                'id': group.id,
                'value': 'group:%s' % group.id,
                'name': group.name,
                'qty_sold': self._as_float(group_sold_qty),
                'is_group': True,
                'parent_group_id': False,
            }]
            for category in children:
                block.append({
                    'id': category.id,
                    'value': 'category:%s' % category.id,
                    'name': '  - %s' % (category.complete_name or category.name),
                    'raw_name': category.complete_name or category.name,
                    'qty_sold': self._as_float(sold_qty_by_category.get(category.id)),
                    'is_group': False,
                    'parent_group_id': group.id,
                })
            ranked_blocks.append((group_sold_qty, group.name or '', group.id, block))

        unmapped_categories = categories.filtered(lambda category: category.id not in grouped_category_ids)
        for category in self._sort_filter_records_by_sold_qty(unmapped_categories, sold_qty_by_category):
            row = {
                'id': category.id,
                'value': 'category:%s' % category.id,
                'name': category.complete_name or category.name,
                'raw_name': category.complete_name or category.name,
                'qty_sold': self._as_float(sold_qty_by_category.get(category.id)),
                'is_group': False,
                'parent_group_id': False,
            }
            ranked_blocks.append((row['qty_sold'], row['name'], row['id'], [row]))

        for _qty, _name, _id, block in sorted(ranked_blocks, key=lambda item: (-item[0], item[1], item[2])):
            rows.extend(block)

        return rows[:limit] if limit else rows

    def _get_category_sold_qty_rollup(self, categories, exact_sold_qty_by_category):
        qty_by_category = {category.id: exact_sold_qty_by_category.get(category.id, 0.0) for category in categories}
        parent_ids_by_category = {}
        for category in categories:
            parent_ids_by_category[category.id] = [
                int(parent_id)
                for parent_id in (category.parent_path or '').split('/')
                if parent_id and int(parent_id) != category.id
            ]
        for category_id, qty in exact_sold_qty_by_category.items():
            for parent_id in parent_ids_by_category.get(category_id, []):
                qty_by_category[parent_id] = qty_by_category.get(parent_id, 0.0) + qty
        return qty_by_category

    def _get_filter_sold_qty_by_template_field(self, field_name):
        column_by_field = {
            'categ_id': 'pt.categ_id',
            'uom_id': 'pt.uom_id',
        }
        column = column_by_field.get(field_name)
        if not column:
            return {}

        qty_by_filter = {}
        self.env.cr.execute(f"""
            SELECT {column} AS filter_id, COALESCE(SUM(sol.product_uom_qty), 0.0) AS qty
              FROM sale_order_line sol
              JOIN product_product pp ON pp.id = sol.product_id
              JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE sol.product_id IS NOT NULL
               AND sol.display_type IS NULL
               AND sol.state IN %s
               AND pt.sale_ok = TRUE
               AND pt.active = TRUE
               AND {column} IS NOT NULL
             GROUP BY {column}
        """, (tuple(['sale', 'done']),))
        for filter_id, qty in self.env.cr.fetchall():
            qty_by_filter[filter_id] = qty_by_filter.get(filter_id, 0.0) + self._as_float(qty)

        if self._has_model('pos.order.line'):
            self.env.cr.execute(f"""
                SELECT {column} AS filter_id, COALESCE(SUM(pol.qty), 0.0) AS qty
                  FROM pos_order_line pol
                  JOIN pos_order po ON po.id = pol.order_id
                  JOIN product_product pp ON pp.id = pol.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                 WHERE pol.product_id IS NOT NULL
                   AND po.state IN %s
                   AND pt.sale_ok = TRUE
                   AND pt.active = TRUE
                   AND {column} IS NOT NULL
                 GROUP BY {column}
            """, (tuple(['paid', 'done', 'invoiced']),))
            for filter_id, qty in self.env.cr.fetchall():
                qty_by_filter[filter_id] = qty_by_filter.get(filter_id, 0.0) + self._as_float(qty)

        return qty_by_filter

    def _sort_filter_records_by_sold_qty(self, records, sold_qty_by_id, limit=False):
        ranked = records.sorted(
            lambda record: (
                -sold_qty_by_id.get(record.id, 0.0),
                getattr(record, 'complete_name', False) or record.display_name or record.name or '',
                record.id,
            )
        )
        return ranked[:limit] if limit else ranked

    def _format_order(self, order):
        if not order:
            return False
        if order.state in ('draft', 'sent') and hasattr(order, '_mqc_ensure_profit_snapshots'):
            order._mqc_ensure_profit_snapshots()
        can_view_cost = self._can_view_cost()
        lines = []
        total_profit_incl_vat = 0.0
        for line in order.order_line.filtered(lambda item: not item.display_type):
            line_profit_total = self._as_float(getattr(line, 'mqc_profit_total_incl_vat_snapshot', 0.0))
            total_profit_incl_vat += line_profit_total
            item = {
                'id': line.id,
                'product_id': line.product_id.id,
                'name': line.name or line.product_id.display_name,
                'quantity': line.product_uom_qty,
                'uom': line.product_uom.name,
                'price_unit': line.price_unit,
                'discount': line.discount,
                'subtotal': line.price_subtotal,
                'total': line.price_total,
                'is_tinted': bool(getattr(line, 'is_tinted_product_line', False)),
                'tinted_done': bool(getattr(line, 'tinted_product_created', False)),
                'profit_per_unit_incl_vat': self._as_float(getattr(line, 'mqc_profit_per_unit_incl_vat_snapshot', 0.0)),
                'profit_total_incl_vat': line_profit_total,
                'profit_snapshot_at': fields.Datetime.to_string(line.mqc_profit_snapshot_at) if getattr(line, 'mqc_profit_snapshot_at', False) else '',
            }
            if can_view_cost:
                quoted_cost = getattr(line, 'quoted_cost_at_creation', 0.0)
                snapshot_cost_incl = self._as_float(getattr(line, 'mqc_profit_cost_unit_incl_vat_snapshot', 0.0))
                line_cost_incl = snapshot_cost_incl or quoted_cost or self._get_line_cost_including_tax(
                    line, self._get_line_cost_excluding_tax(line)
                )
                line_cost_incl = self._as_float(line_cost_incl)
                item.update({
                    'quoted_cost': quoted_cost,
                    'purchase_price': getattr(line, 'purchase_price', 0.0),
                    'cost_incl_vat': line_cost_incl,
                })
            lines.append(item)
        return {
            'id': order.id,
            'name': order.name,
            'state': order.state,
            'partner_id': order.partner_id.id,
            'partner_name': order.partner_id.display_name,
            'pricelist_id': order.pricelist_id.id,
            'warehouse_id': order.warehouse_id.id if order.warehouse_id else False,
            'currency': order.currency_id.symbol or order.currency_id.name,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'amount_total': order.amount_total,
            'profit_total_incl_vat': total_profit_incl_vat,
            'lines': lines,
        }

    def _get_sale_price(self, product, filters):
        pricelist_id = filters.get('pricelist_id')
        partner_id = filters.get('partner_id')
        quantity = float(filters.get('quantity') or 1.0)
        pricelist = self.env['product.pricelist'].browse(pricelist_id).exists() if pricelist_id else False
        partner = self.env['res.partner'].browse(partner_id).exists() if partner_id else self.env.user.partner_id
        if pricelist:
            try:
                return pricelist._get_product_price(product, quantity, partner)
            except Exception as exc:
                self._log_head('PRICE FALLBACK', 'pricelist price failed', level='warning', product_id=product.id, error=str(exc))
        return product.lst_price

    def _get_product_cost_in_order_currency(self, product, filters):
        cost = product.standard_price or 0.0
        currency = product.company_id.currency_id or self.env.company.currency_id
        target_currency = currency
        pricelist = self.env['product.pricelist'].browse(filters.get('pricelist_id')).exists() if filters.get('pricelist_id') else False
        if pricelist and pricelist.currency_id:
            target_currency = pricelist.currency_id
        if currency != target_currency:
            cost = currency._convert(cost, target_currency, self.env.company, fields.Date.context_today(self))
        return cost

    def _get_cost_including_tax(self, product, cost_excl):
        cost_excl = self._as_float(cost_excl)
        taxes = product.taxes_id.filtered(lambda tax: not tax.company_id or tax.company_id == self.env.company)
        if not taxes:
            return cost_excl
        try:
            tax_result = taxes.compute_all(
                cost_excl,
                currency=self.env.company.currency_id,
                quantity=1.0,
                product=product,
                partner=False,
                handle_price_include=False,
            )
            return self._as_float(tax_result.get('total_included'), cost_excl)
        except Exception as exc:
            self._log_head('COST TAX FALLBACK', 'tax computation failed', level='warning', product_id=product.id, error=str(exc))
            return cost_excl

    def _get_line_cost_excluding_tax(self, line):
        quoted_cost = getattr(line, 'quoted_cost_at_creation', 0.0)
        if quoted_cost:
            return quoted_cost
        cost = getattr(line, 'purchase_price', 0.0) or line.product_id.standard_price or 0.0
        if line.product_id.uom_id and line.product_uom and line.product_id.uom_id != line.product_uom:
            cost = line.product_id.uom_id._compute_price(cost, line.product_uom)
        return cost

    def _get_line_cost_including_tax(self, line, cost_excl):
        cost_excl = self._as_float(cost_excl)
        taxes = line.tax_id or line.product_id.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == line.order_id.company_id
        )
        if not taxes:
            return cost_excl
        try:
            tax_result = taxes.compute_all(
                cost_excl,
                currency=line.currency_id,
                quantity=1.0,
                product=line.product_id,
                partner=line.order_id.partner_shipping_id or line.order_id.partner_id,
                handle_price_include=False,
            )
            return self._as_float(tax_result.get('total_included'), cost_excl)
        except Exception as exc:
            self._log_head('LINE COST TAX FALLBACK', 'tax computation failed', level='warning', line_id=line.id, error=str(exc))
            return cost_excl

    def _get_product_warning_flags(self, product):
        flags = []
        if product.qty_available <= 0:
            flags.append('no_stock')
        elif product.virtual_available <= 0:
            flags.append('forecast_shortage')
        return flags

    def _name_list(self, records):
        return [{'id': rec.id, 'name': rec.display_name} for rec in records]

    def _as_float(self, value, fallback=0.0):
        try:
            return float(value if value is not None else fallback)
        except (TypeError, ValueError):
            return float(fallback or 0.0)
