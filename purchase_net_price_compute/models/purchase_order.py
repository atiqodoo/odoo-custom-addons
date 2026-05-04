# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    has_custom_pricing_lines = fields.Boolean(
        string="Has Custom Pricing Lines",
        compute='_compute_has_custom_pricing_lines',
        store=True
    )

    @api.depends('order_line.use_custom_pricing')
    def _compute_has_custom_pricing_lines(self):
        for order in self:
            order.has_custom_pricing_lines = any(line.use_custom_pricing for line in order.order_line)

    def action_create_invoice_wizard(self):
        self.ensure_one()
        _logger.info(f"Creating invoice wizard for PO {self.name}")
        line_vals = []
        for line in self.order_line.filtered(lambda l: l.product_id):
            # Check ProductVendorPricing
            domain = [
                ('partner_id', '=', self.partner_id.id),
                '|',
                ('product_id', '=', line.product_id.id),
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ('min_qty', '<=', line.product_qty),
                '|',
                ('max_qty', '=', 0.0),
                ('max_qty', '>=', line.product_qty),
                ('active', '=', True),
            ]
            pricing_rule = self.env['product.vendor.pricing'].search(domain, limit=1, order='min_qty desc')
            product_tmpl = line.product_id.product_tmpl_id
            try:
                if pricing_rule:
                    _logger.debug(f"Found pricing rule for {line.product_id.display_name}: Discount={pricing_rule.discount_percentage}%, Freight={pricing_rule.freight_percentage}%")
                    use_custom_pricing = True
                    applied_discount = pricing_rule.discount_percentage or 0.0
                    applied_freight = pricing_rule.freight_percentage or 0.0
                    # vendor_price = pricing_rule.price_unit if pricing_rule.price_unit > 0 else line.price_unit  # Removed
                else:
                    _logger.debug(f"No pricing rule found for {line.product_id.display_name}, using product.template defaults")
                    use_custom_pricing = (product_tmpl.default_discount_percentage or 0.0) > 0 or (product_tmpl.default_freight_percentage or 0.0) > 0
                    applied_discount = product_tmpl.default_discount_percentage or 0.0
                    applied_freight = product_tmpl.default_freight_percentage or 0.0
                    # vendor_price = line.price_unit or 0.0  # Removed

                line_vals.append((0, 0, {
                    'product_id': line.product_id.id,
                    'product_qty': line.product_qty,
                    'price_unit': line.price_unit,
                    'vendor_price': False,  # Explicitly set to blank
                    'use_custom_pricing': use_custom_pricing,
                    'applied_discount': applied_discount,
                    'applied_freight': applied_freight,
                    'purchase_line_id': line.id,
                    'currency_id': self.currency_id.id,
                }))
            except Exception as e:
                _logger.error(f"Error initializing wizard line for {line.product_id.display_name}: {str(e)}")
                continue
        
        if not line_vals:
            _logger.warning(f"No valid lines to create wizard for PO {self.name}")
            return {'type': 'ir.actions.do_nothing'}

        wizard = self.env['vendor.price.wizard'].create({
            'purchase_id': self.id,
            'line_ids': line_vals
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vendor.price.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    @api.depends('order_line.price_total', 'has_custom_pricing_lines')
    def _compute_amount_all(self):
        """
        Override to ensure totals reflect the adjusted amounts from order lines
        """
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            
            # Only override if any line has custom pricing enabled
            if order.has_custom_pricing_lines:
                order.amount_untaxed = sum(order_lines.mapped('price_subtotal'))
                order.amount_tax = sum(order_lines.mapped('price_tax'))
                order.amount_total = sum(order_lines.mapped('price_total'))
            else:
                # Use standard Odoo calculation
                super(PurchaseOrder, order)._compute_amount_all()

    @api.depends(
        'order_line.price_subtotal',
        'order_line.price_tax',
        'order_line.price_total',
        'has_custom_pricing_lines',
    )
    def _compute_tax_totals(self):
        """
        Override to ensure tax_totals JSON reflects the adjusted amounts
        """
        for order in self:
            # If no custom pricing lines, use standard calculation
            if not order.has_custom_pricing_lines:
                super(PurchaseOrder, order)._compute_tax_totals()
                continue
            
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            
            # Calculate totals from adjusted line amounts
            base_amount = sum(order_lines.mapped('price_subtotal'))
            tax_amount = sum(order_lines.mapped('price_tax'))
            total_amount = base_amount + tax_amount
            
            # Group taxes by tax group
            tax_groups_data = {}
            for line in order_lines:
                if not line.taxes_id:
                    continue
                    
                for tax in line.taxes_id:
                    group_key = tax.tax_group_id.id
                    if group_key not in tax_groups_data:
                        tax_groups_data[group_key] = {
                            'id': group_key,
                            'involved_tax_ids': [],
                            'tax_amount_currency': 0.0,
                            'tax_amount': 0.0,
                            'base_amount_currency': 0.0,
                            'base_amount': 0.0,
                            'display_base_amount_currency': 0.0,
                            'display_base_amount': 0.0,
                            'group_name': tax.tax_group_id.name or '',
                            'group_label': False,
                        }
                    
                    if tax.id not in tax_groups_data[group_key]['involved_tax_ids']:
                        tax_groups_data[group_key]['involved_tax_ids'].append(tax.id)
                    
                    tax_groups_data[group_key]['base_amount_currency'] += line.price_subtotal
                    tax_groups_data[group_key]['base_amount'] += line.price_subtotal
                    tax_groups_data[group_key]['display_base_amount_currency'] += line.price_subtotal
                    tax_groups_data[group_key]['display_base_amount'] += line.price_subtotal
                    tax_groups_data[group_key]['tax_amount_currency'] += line.price_tax
                    tax_groups_data[group_key]['tax_amount'] += line.price_tax

            # Build tax_totals structure
            order.tax_totals = {
                'currency_id': order.currency_id.id,
                'currency_pd': order.currency_id.decimal_places or 2,
                'company_currency_id': order.company_id.currency_id.id,
                'company_currency_pd': order.company_id.currency_id.decimal_places or 2,
                'has_tax_groups': bool(tax_groups_data),
                'subtotals': [{
                    'tax_groups': list(tax_groups_data.values()) if tax_groups_data else [],
                    'tax_amount_currency': tax_amount,
                    'tax_amount': tax_amount,
                    'base_amount_currency': base_amount,
                    'base_amount': base_amount,
                    'name': 'Untaxed Amount',
                }],
                'base_amount_currency': base_amount,
                'base_amount': base_amount,
                'tax_amount_currency': tax_amount,
                'tax_amount': tax_amount,
                'same_tax_base': True,
                'total_amount_currency': total_amount,
                'total_amount': total_amount,
                'groups_by_subtotal': {},
                'allow_tax_edition': False,
            }