import logging

from odoo import _, models
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class PurchaseVariantMatching(models.AbstractModel):
    _name = 'purchase.variant.matching'
    _description = 'Purchase variant matching adapter'

    def _catalogue(self):
        return self.env['modern.quotation.catalogue.service']

    def _default_filters(self, product):
        catalogue = self._catalogue()
        return {
            'category_id': product.categ_id.id,
            'use_category_group': False,
            'category_group_id': self.env['modern.quotation.category.group'].search([
                ('active', '=', True), ('child_category_ids', 'in', product.categ_id.ids),
            ], limit=1).id,
            'colour_group_id': catalogue._get_product_colour_attribute_group(product).id,
            'uom_id': product.uom_id.id,
        }

    def _base_domain(self, wizard):
        """Category/UoM scope shared by strict matching and its fallback."""
        domain = [
            ('active', '=', True), ('purchase_ok', '=', True), ('is_storable', '=', True),
            ('company_id', 'in', [False, wizard.company_id.id]),
            ('uom_id', '=', wizard.uom_id.id),
        ]
        category_filter = ('group:%s' % wizard.category_group_id.id if wizard.use_category_group
                           else wizard.category_id.id)
        domain += self._catalogue()._get_category_filter_domain({'category_filter': category_filter})
        return domain

    def _domain(self, wizard):
        """Reuse catalogue mapping records, with purchase eligibility and company scoping."""
        domain = self._base_domain(wizard)
        group = wizard.colour_group_id
        if group:
            terms = []
            if group.colour_code_ids:
                terms.append([('product_tmpl_id.colour_code_id', 'in', group.colour_code_ids.ids)])
            if group.attribute_value_ids:
                terms.append([('product_template_attribute_value_ids.product_attribute_value_id',
                               'in', group.attribute_value_ids.ids)])
            return expression.AND([domain, expression.OR(terms) if terms else [('id', '=', 0)]])
        product = wizard.product_id
        if product.colour_code_id:
            return domain + [('product_tmpl_id.colour_code_id', '=', product.colour_code_id.id)]
        values = product.product_template_attribute_value_ids.product_attribute_value_id
        if values:
            # No mapping: require every original attribute instead of silently matching other colours.
            return domain + [
                ('product_template_attribute_value_ids.product_attribute_value_id', 'in', [value.id])
                for value in values
            ]
        return domain + [('id', '=', product.id)]

    def _match_description(self, wizard, category_fallback=False):
        if category_fallback:
            return _('Category/UoM fallback: no colour/attribute alternatives were found. Showing the selected category scope and exact stock UoM; colours and attributes may differ.')
        if wizard.colour_group_id:
            return _('Mapped colour/attribute group: %s') % wizard.colour_group_id.display_name
        if wizard.product_id.colour_code_id:
            return _('Exact colour code; no equivalence group configured.')
        if wizard.product_id.product_template_attribute_value_ids:
            return _('Exact original attributes; no colour equivalence group configured.')
        return _('No colour or attribute mapping available. Only the original product is shown.')

    def _find(self, wizard):
        _logger.debug('[RFQ_STOCK_COMPARE][MATCH][START] product_id=%s company_id=%s category_id=%s use_category_group=%s category_group_id=%s',
                      wizard.product_id.id, wizard.company_id.id, wizard.category_id.id,
                      wizard.use_category_group, wizard.category_group_id.id if wizard.use_category_group else False)
        try:
            raw_limit = self.env['ir.config_parameter'].sudo().get_param(
                'purchase_variant_stock_compare.result_limit', '80')
            limit = max(1, int(raw_limit))
            Product = self.env['product.product']
            products = Product.search(self._domain(wizard), order='name, id', limit=limit + 1)
            # The selected product matching itself is not an alternative. Broaden
            # only when no other eligible colour/attribute match exists, regardless
            # of stock quantity (zero-stock matches still count as matches).
            category_fallback = not (products - wizard.product_id)
            if category_fallback:
                products = Product.search(self._base_domain(wizard), order='name, id', limit=limit + 1)
            _logger.debug('[RFQ_STOCK_COMPARE][MATCH][END] count=%s truncated=%s category_fallback=%s',
                          len(products), len(products) > limit, category_fallback)
            return products[:limit], len(products) > limit, category_fallback
        except Exception:
            _logger.exception('[RFQ_STOCK_COMPARE][MATCH][ERROR] product_id=%s company_id=%s',
                              wizard.product_id.id, wizard.company_id.id)
            raise
