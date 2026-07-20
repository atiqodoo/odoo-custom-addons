# -*- coding: utf-8 -*-

import base64
import io
import logging
from datetime import datetime, time

from odoo import fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

_logger = logging.getLogger(__name__)


class StockCardWizardContactBase(models.TransientModel):
    _inherit = 'stock.card.wizard'

    report_mode = fields.Selection(
        [
            ('product_stock_card', 'Product Stock Card'),
            ('contact_transactions', 'Contact Transactions'),
        ],
        string='Report Mode',
        default='product_stock_card',
        required=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        help='Search transactions for this contact and all child contacts under the same commercial partner.',
    )
    include_draft_sales = fields.Boolean(
        string='Include Draft Sales',
        default=True,
        help='Include quotations and draft sales orders that do not yet have stock moves.',
    )
    include_contact_pos = fields.Boolean(string='Include POS', default=True)
    include_contact_sales = fields.Boolean(string='Include Sales', default=True)
    include_contact_stock_moves = fields.Boolean(string='Include Stock Moves', default=True)
    include_contact_mrp = fields.Boolean(string='Include Manufacturing', default=True)

    def action_print_pdf(self):
        self.ensure_one()
        if self.report_mode != 'contact_transactions':
            return super().action_print_pdf()

        _logger.info("=" * 80)
        _logger.info("[CONTACT REPORT] ACTION: PRINT PDF CLICKED")
        data = self._prepare_contact_transaction_data()
        _logger.info("[CONTACT REPORT] PDF rows prepared: %s", len(data.get('rows', [])))
        result = self.env.ref('enhanced_stock_card.action_report_stock_card').report_action(self, data=data)
        _logger.info("[CONTACT REPORT] PDF report action returned: %s", result)
        _logger.info("=" * 80)
        return result

    def action_export_excel(self):
        self.ensure_one()
        if self.report_mode != 'contact_transactions':
            return super().action_export_excel()

        _logger.info("=" * 80)
        _logger.info("[CONTACT REPORT] ACTION: EXPORT EXCEL CLICKED")
        if not xlsxwriter:
            _logger.error("[CONTACT REPORT] xlsxwriter not installed")
            raise UserError(_('Please install xlsxwriter Python library: pip install xlsxwriter'))

        data = self._prepare_contact_transaction_data()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._create_excel_report(workbook, data)
        workbook.close()
        output.seek(0)

        safe_partner = (self.partner_id.display_name or 'contact').replace('/', '-')
        export_stamp = fields.Datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"contact_transactions_{safe_partner}_{self.date_from}_{self.date_to}_{export_stamp}.xlsx"
        self.write({
            'excel_file': base64.b64encode(output.read()),
            'excel_filename': filename,
        })
        _logger.info(
            "[CONTACT REPORT] Excel file created with Unit Price Incl VAT column and VAT-inclusive Inventory Value: %s",
            filename,
        )
        _logger.info("=" * 80)

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=stock.card.wizard&id={self.id}&field=excel_file&download=true&filename={filename}',
            'target': 'new',
        }

    def _prepare_stock_card_data(self):
        self.ensure_one()
        if self.report_mode == 'contact_transactions':
            return self._prepare_contact_transaction_data()
        return super()._prepare_stock_card_data()

    def _prepare_contact_transaction_data(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Please select a contact for Contact Transactions mode.'))

        _logger.info("=" * 80)
        _logger.info("[CONTACT REPORT] PREPARING CONTACT TRANSACTION DATA")
        _logger.info("[CONTACT REPORT] Contact: %s (ID: %s)", self.partner_id.display_name, self.partner_id.id)
        _logger.info("[CONTACT REPORT] Products filter: %s", self.product_ids.mapped('display_name'))
        _logger.info("[CONTACT REPORT] Locations filter: %s", self.location_ids.mapped('complete_name'))
        _logger.info("[CONTACT REPORT] Date range: %s to %s", self.date_from, self.date_to)

        partner_ids = self._get_contact_partner_ids()
        rows = []
        source_counts = {}

        collectors = [
            ('POS', self.include_contact_pos, self._collect_contact_pos_rows),
            ('Sales', self.include_contact_sales, self._collect_contact_sale_rows),
            ('Stock Moves', self.include_contact_stock_moves, self._collect_contact_stock_move_rows),
            ('Manufacturing', self.include_contact_mrp, self._collect_contact_mrp_rows),
        ]

        for source_name, enabled, collector in collectors:
            if not enabled:
                _logger.info("[CONTACT REPORT] Source skipped by option: %s", source_name)
                continue
            try:
                source_rows = collector(partner_ids)
                rows.extend(source_rows)
                source_counts[source_name] = len(source_rows)
                _logger.info("[CONTACT REPORT] Source %s returned %s row(s)", source_name, len(source_rows))
            except Exception:
                _logger.exception("[CONTACT REPORT] Source %s failed", source_name)
                raise

        self._normalize_contact_vat_values(rows)
        rows.sort(key=lambda row: (row.get('date') or datetime.min, row.get('source_document') or '', row.get('product') or ''))
        self._apply_contact_running_balances(rows)

        _logger.info("[CONTACT REPORT] Final row count: %s", len(rows))
        _logger.info("[CONTACT REPORT] Source counts: %s", source_counts)
        _logger.info("=" * 80)
        return {
            'report_mode': 'contact_transactions',
            'wizard': self,
            'partner': self.partner_id,
            'commercial_partner': self.partner_id.commercial_partner_id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'locations': self.location_ids,
            'products': self.product_ids,
            'rows': rows,
            'source_counts': source_counts,
            'company': self.env.company,
        }

    def _get_contact_partner_ids(self):
        commercial_partner = self.partner_id.commercial_partner_id
        partners = self.env['res.partner'].search([
            ('commercial_partner_id', '=', commercial_partner.id),
        ])
        _logger.info(
            "[CONTACT REPORT] Commercial partner: %s (ID: %s), partner IDs included: %s",
            commercial_partner.display_name,
            commercial_partner.id,
            partners.ids,
        )
        return partners.ids

    def _contact_date_range(self):
        return (
            datetime.combine(self.date_from, time.min),
            datetime.combine(self.date_to, time.max),
        )

    def _contact_product_allowed(self, product):
        return not self.product_ids or product in self.product_ids

    def _contact_move_location_allowed(self, move):
        if not self.location_ids:
            return True
        location_ids = self.location_ids.ids
        return move.location_id.id in location_ids or move.location_dest_id.id in location_ids

    def _contact_row(self, **values):
        defaults = {
            'date': False,
            'contact': '',
            'product': '',
            'product_id': False,
            'source_app': '',
            'source_document': '',
            'document_state': '',
            'transaction_type': '',
            'qty_in': 0.0,
            'qty_out': 0.0,
            'balance_qty': 0.0,
            'inventory_value': 0.0,
            'unit_price_incl_vat': 0.0,
            'selling_price_incl_vat': 0.0,
            'amount_incl_vat': 0.0,
            'vat_amount': 0.0,
            'location': '',
            'reference': '',
            'debug_source': '',
        }
        defaults.update(values)
        return defaults

    def _normalize_contact_vat_values(self, rows):
        """Use Odoo product cost plus configured VAT as the contact inventory value."""
        for row in rows:
            original_inventory_value = row.get('inventory_value') or 0.0
            quantity = max(abs(row.get('qty_in') or 0.0), abs(row.get('qty_out') or 0.0))
            product = row.get('product_id')
            unit_cost_incl_vat = self._get_product_cost_incl_vat(product) if product else 0.0
            value_basis = unit_cost_incl_vat * quantity if quantity and unit_cost_incl_vat else original_inventory_value

            row['inventory_value'] = value_basis
            row['unit_price_incl_vat'] = unit_cost_incl_vat if unit_cost_incl_vat else (value_basis / quantity if quantity else 0.0)
            row['selling_price_incl_vat'] = (row.get('amount_incl_vat') or 0.0) / quantity if quantity else 0.0

            _logger.info(
                "[CONTACT REPORT] Cost/Selling VAT normalized source=%s doc=%s product=%s qty=%s standard_price=%s original_inventory=%s display_inventory=%s unit_cost_incl_vat=%s selling_price_incl_vat=%s amount_incl_vat=%s",
                row.get('source_app'),
                row.get('source_document'),
                row.get('product'),
                quantity,
                product.standard_price if product else 0.0,
                original_inventory_value,
                row['inventory_value'],
                row['unit_price_incl_vat'],
                row['selling_price_incl_vat'],
                row.get('amount_incl_vat') or 0.0,
            )

    def _get_product_cost_incl_vat(self, product):
        if not product:
            return 0.0

        unit_cost = product.standard_price or 0.0
        taxes = product.supplier_taxes_id.filtered(lambda tax: tax.company_id in (False, self.env.company))
        if not taxes:
            taxes = product.taxes_id.filtered(lambda tax: tax.company_id in (False, self.env.company))

        if not taxes:
            _logger.info(
                "[CONTACT REPORT] No tax configured for product %s; cost incl VAT equals standard_price %s",
                product.display_name,
                unit_cost,
            )
            return unit_cost

        tax_result = taxes.compute_all(
            unit_cost,
            currency=self.env.company.currency_id,
            quantity=1.0,
            product=product,
            partner=self.partner_id,
        )
        unit_cost_incl_vat = tax_result.get('total_included', unit_cost)
        _logger.info(
            "[CONTACT REPORT] Product cost incl VAT product=%s standard_price=%s taxes=%s total_included=%s",
            product.display_name,
            unit_cost,
            taxes.mapped('name'),
            unit_cost_incl_vat,
        )
        return unit_cost_incl_vat

    def _apply_contact_running_balances(self, rows):
        balances = {}
        for row in rows:
            product = row.get('product') or ''
            balances.setdefault(product, 0.0)
            balances[product] += row.get('qty_in', 0.0) - row.get('qty_out', 0.0)
            row['balance_qty'] = balances[product]
