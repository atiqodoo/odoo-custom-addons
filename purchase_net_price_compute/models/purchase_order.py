# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools.misc import html_escape
from odoo.tools.float_utils import float_is_zero
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    vendor_promised_cost_contact = fields.Char(
        string="Vendor Sales/Customer Service Contact",
        readonly=True,
        tracking=True,
        index=True,
        help=(
            "Legacy text snapshot of the selected vendor sales or customer "
            "service contact."
        ),
    )

    has_custom_pricing_lines = fields.Boolean(
        string="Has Custom Pricing Lines",
        compute='_compute_has_custom_pricing_lines',
        store=True
    )
    lpo_grade_volume_summary = fields.Text(
        string="Grade Volume Summary",
        compute='_compute_lpo_grade_volume_summary',
        store=True,
        readonly=True,
        tracking=True,
        help="Gross order volume and VAT-inclusive value grouped by movement-volume reporting grade.",
    )
    lpo_grade_volume_summary_json = fields.Json(
        string="Grade Volume Summary Snapshot",
        compute='_compute_lpo_grade_volume_summary',
        store=True,
        readonly=True,
        help="Stored grade-wise volume and VAT-inclusive value snapshot for later vendor bill comparison.",
    )

    @api.depends('order_line.use_custom_pricing')
    def _compute_has_custom_pricing_lines(self):
        for order in self:
            order.has_custom_pricing_lines = any(line.use_custom_pricing for line in order.order_line)

    @api.depends(
        'order_line.volume_reporting_grade_id',
        'order_line.order_line_grade_volume',
        'order_line.volume_reference_uom_id',
        'order_line.price_total',
        'order_line.display_type',
        'currency_id',
    )
    def _compute_lpo_grade_volume_summary(self):
        for order in self:
            totals = {}
            for line in order.order_line.filtered(
                lambda item: (
                    not item.display_type
                    and item.product_id
                    and (item.order_line_grade_volume or item.price_total)
                )
            ):
                grade_id = line.volume_reporting_grade_id.id or False
                grade_name = (
                    line.volume_reporting_grade_id.display_name
                    if line.volume_reporting_grade_id
                    else _('Unmapped Grade')
                )
                uom_name = line.volume_reference_uom_id.name or ''
                uom_id = line.volume_reference_uom_id.id or False
                key = (grade_id, grade_name, uom_id, uom_name)
                if key not in totals:
                    totals[key] = {
                        'grade_id': grade_id,
                        'grade_name': grade_name,
                        'uom_id': uom_id,
                        'uom_name': uom_name,
                        'volume': 0.0,
                        'amount_vat_incl': 0.0,
                        'currency_id': order.currency_id.id,
                        'currency_name': order.currency_id.name,
                    }
                totals[key]['volume'] += line.order_line_grade_volume or 0.0
                totals[key]['amount_vat_incl'] += line.price_total or 0.0

            lines = []
            snapshot = []
            for key, values in sorted(totals.items(), key=lambda item: (item[0][1], item[0][3])):
                volume_text = order._lpo_report_format_float(values['volume'], 2)
                volume_suffix = f" {values['uom_name']}" if values['uom_name'] else ""
                amount_text = order._lpo_format_grade_amount(values['amount_vat_incl'])
                lines.append(
                    _(
                        "%(grade)s Grade Gross Volume: %(volume)s%(uom)s / %(amount)s VAT Incl.",
                        grade=values['grade_name'],
                        volume=volume_text,
                        uom=volume_suffix,
                        amount=amount_text,
                    )
                )
                snapshot.append({
                    'grade_id': values['grade_id'],
                    'grade_name': values['grade_name'],
                    'uom_id': values['uom_id'],
                    'uom_name': values['uom_name'],
                    'volume': values['volume'],
                    'amount_vat_incl': values['amount_vat_incl'],
                    'currency_id': values['currency_id'],
                    'currency_name': values['currency_name'],
                })
            order.lpo_grade_volume_summary = "\n".join(lines)
            order.lpo_grade_volume_summary_json = snapshot

    def _lpo_format_grade_amount(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        rounded_amount = currency.round(amount or 0.0) if currency else amount or 0.0
        return f"{currency.name} {rounded_amount:,.2f}" if currency else f"{rounded_amount:,.2f}"

    @api.onchange('order_line')
    def _onchange_lpo_grade_volume_summary(self):
        self.order_line._compute_lpo_grade_volume_fields()
        self._compute_lpo_grade_volume_summary()

    def _post_lpo_grade_volume_summary_change(self, previous_summaries):
        for order in self:
            previous = previous_summaries.get(order.id) or ''
            current = order.lpo_grade_volume_summary or ''
            if previous == current:
                continue
            body = _(
                "<b>Grade Volume Summary Updated</b><br/>%(summary)s",
                summary=html_escape(current).replace('\n', '<br/>') if current else _('No grade volumes.'),
            )
            order.message_post(body=body)

    def write(self, vals):
        previous_summaries = {
            order.id: order.lpo_grade_volume_summary
            for order in self
        } if 'order_line' in vals else {}
        result = super(PurchaseOrder, self.with_context(
            skip_lpo_grade_volume_line_chatter=True
        )).write(vals)
        if previous_summaries:
            self._post_lpo_grade_volume_summary_change(previous_summaries)
        return result

    def _get_invoice_wizard_received_qty(self, po_line):
        received_to_bill = max((po_line.qty_received or 0.0) - (po_line.qty_invoiced or 0.0), 0.0)
        rounding = po_line.product_uom.rounding if po_line.product_uom else 0.01
        return 0.0 if float_is_zero(received_to_bill, precision_rounding=rounding) else received_to_bill

    def action_create_invoice_wizard(self):
        self.ensure_one()
        _logger.info(f"Creating invoice wizard for PO {self.name}")
        line_vals = []
        for line in self.order_line.filtered(lambda l: l.product_id):
            received_qty = self._get_invoice_wizard_received_qty(line)
            if not received_qty:
                _logger.info(
                    "Skipping %s on PO %s: received=%s, already invoiced=%s",
                    line.product_id.display_name,
                    self.name,
                    line.qty_received,
                    line.qty_invoiced,
                )
                continue
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
                    'product_qty': received_qty,
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
