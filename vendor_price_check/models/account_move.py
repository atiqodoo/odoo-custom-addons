# vendor_price_check/models/account_move.py
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

from odoo.addons.vendor_price_check.services.vendor_bill_price_checker import (
    VendorBillFinalUnitPriceChecker,
)

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    # ══════════════════════════════════════════════════════════════════════════
    # FIELDS
    # ══════════════════════════════════════════════════════════════════════════
    
    discrepancy_count = fields.Integer(
        compute='_compute_discrepancy_count', 
        string="Discrepancy Count", 
        store=True
    )
    
    discrepancy_ids = fields.One2many(
        'vendor.price.discrepancy', 
        'bill_id', 
        string="Discrepancies"
    )
    
    discrepancy_approved = fields.Boolean(
        string="Discrepancy Approved"
    )
    
    subtotal_incl_vat = fields.Monetary(
        string="Subtotal (incl. VAT)",
        compute='_compute_subtotal_incl_vat',
        store=True,
        readonly=True,
        currency_field='currency_id',
        help="Total of all invoice lines including taxes (price_subtotal + tax)."
    )

    promised_cost_diff_count = fields.Integer(
        string="Promised Cost Diff Count",
        compute='_compute_promised_cost_diff_count',
    )

    invoice_variance_audit_ids = fields.One2many(
        'vendor.bill.invoice.variance.audit',
        'bill_id',
        string='Invoice Variance Audits',
    )

    invoice_variance_audit_count = fields.Integer(
        string='Invoice Variance Audit Count',
        compute='_compute_invoice_variance_audit_count',
    )

    bill_grade_volume_summary = fields.Text(
        string='Bill Grade Volume Summary',
        compute='_compute_bill_grade_volume_summary',
        store=True,
        readonly=True,
        tracking=True,
    )

    bill_grade_volume_summary_json = fields.Json(
        string='Bill Grade Volume Summary Snapshot',
        compute='_compute_bill_grade_volume_summary',
        store=True,
        readonly=True,
        help='Stored bill grade-wise volume and VAT-inclusive value snapshot from vendor price wizard lines.',
    )

    # ══════════════════════════════════════════════════════════════════════════
    # COMPUTE METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    @api.depends('discrepancy_ids')
    def _compute_discrepancy_count(self):
        """
        Compute the total number of price discrepancies for this bill.
        Updates whenever discrepancy_ids changes.
        """
        for move in self:
            move.discrepancy_count = len(move.discrepancy_ids)
            _logger.debug(
                "Computed discrepancy count for bill %s: %s", 
                move.name or 'Unnamed', 
                move.discrepancy_count
            )

    @api.depends('invoice_line_ids.price_total')
    def _compute_subtotal_incl_vat(self):
        """
        Calculate subtotal including VAT.
        price_total = price_subtotal + tax amount (already computed by Odoo).
        We simply sum it for all real invoice lines.
        """
        for move in self:
            total = sum(
                line.price_total
                for line in move.invoice_line_ids
                if not line.display_type
            )
            move.subtotal_incl_vat = total

    @api.depends(
        'invoice_line_ids.vendor_promised_cost_vat_incl',
        'invoice_line_ids.promised_cost_difference_vat_incl',
        'invoice_line_ids.display_type',
    )
    def _compute_promised_cost_diff_count(self):
        for move in self:
            rounding = move.currency_id.rounding or 0.01
            move.promised_cost_diff_count = len(move.invoice_line_ids.filtered(
                lambda line: (
                    line.display_type not in ('line_section', 'line_note')
                    and line.vendor_promised_cost_vat_incl
                    and abs(line.promised_cost_difference_vat_incl) > rounding
                )
            ))

    @api.depends('invoice_variance_audit_ids')
    def _compute_invoice_variance_audit_count(self):
        for move in self:
            move.invoice_variance_audit_count = len(move.invoice_variance_audit_ids)

    @api.depends(
        'invoice_line_ids.vpc_from_vendor_price_wizard',
        'invoice_line_ids.bill_volume_reporting_grade_id',
        'invoice_line_ids.bill_volume_reference_uom_id',
        'invoice_line_ids.bill_grade_volume',
        'invoice_line_ids.bill_grade_amount_vat_incl',
        'invoice_line_ids.display_type',
    )
    def _compute_bill_grade_volume_summary(self):
        for move in self:
            totals = {}
            for line in move.invoice_line_ids.filtered(
                lambda item: (
                    item.display_type not in ('line_section', 'line_note')
                    and item.purchase_line_id
                    and (item.bill_grade_volume or item.bill_grade_amount_vat_incl)
                )
            ):
                grade_id = line.bill_volume_reporting_grade_id.id or False
                grade_name = (
                    line.bill_volume_reporting_grade_id.display_name
                    if line.bill_volume_reporting_grade_id
                    else _('Unmapped Grade')
                )
                uom_id = line.bill_volume_reference_uom_id.id or False
                uom_name = line.bill_volume_reference_uom_id.name or ''
                currency = line.currency_id or move.currency_id or move.company_id.currency_id
                key = (grade_id, grade_name, uom_id, uom_name, currency.id)
                if key not in totals:
                    totals[key] = {
                        'grade_id': grade_id,
                        'grade_name': grade_name,
                        'uom_id': uom_id,
                        'uom_name': uom_name,
                        'volume': 0.0,
                        'amount_vat_incl': 0.0,
                        'currency_id': currency.id,
                        'currency_name': currency.name,
                    }
                totals[key]['volume'] += line.bill_grade_volume or 0.0
                totals[key]['amount_vat_incl'] += line.bill_grade_amount_vat_incl or 0.0

            lines = []
            snapshot = []
            volume_totals = {}
            amount_total = 0.0
            formatter_order = move.purchase_id or move.invoice_line_ids.purchase_line_id.order_id[:1]
            for key, values in sorted(totals.items(), key=lambda item: (item[0][1], item[0][3])):
                currency = self.env['res.currency'].browse(values['currency_id'])
                amount = currency.round(values['amount_vat_incl']) if currency else values['amount_vat_incl']
                amount_text = f"{values['currency_name']} {amount:,.2f}"
                volume_text = (
                    formatter_order._lpo_report_format_float(values['volume'], 2)
                    if formatter_order
                    else f"{values['volume']:,.2f}".rstrip('0').rstrip('.')
                )
                volume_suffix = f" {values['uom_name']}" if values['uom_name'] else ''
                lines.append(
                    _(
                        "%(grade)s Grade Billed Volume: %(volume)s%(uom)s / %(amount)s VAT Incl.",
                        grade=values['grade_name'],
                        volume=volume_text,
                        uom=volume_suffix,
                        amount=amount_text,
                    )
                )
                snapshot.append(values)
                volume_totals[values['uom_name']] = volume_totals.get(values['uom_name'], 0.0) + values['volume']
                amount_total += values['amount_vat_incl']

            if snapshot:
                default_currency = move.currency_id or move.company_id.currency_id
                if len({item['currency_id'] for item in snapshot}) == 1:
                    default_currency = self.env['res.currency'].browse(snapshot[0]['currency_id'])
                volume_parts = []
                for uom_name, volume in sorted(volume_totals.items()):
                    volume_text = (
                        formatter_order._lpo_report_format_float(volume, 2)
                        if formatter_order
                        else f"{volume:,.2f}".rstrip('0').rstrip('.')
                    )
                    volume_parts.append(f"{volume_text} {uom_name}".strip())
                amount_total = default_currency.round(amount_total) if default_currency else amount_total
                lines.append(
                    _(
                        "TOTAL Grade Billed: %(volume)s / %(amount)s VAT Incl.",
                        volume=", ".join(volume_parts),
                        amount=(
                            f"{default_currency.name} {amount_total:,.2f}"
                            if default_currency
                            else f"{amount_total:,.2f}"
                        ),
                    )
                )

            move.bill_grade_volume_summary = "\n".join(lines)
            move.bill_grade_volume_summary_json = snapshot

    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _check_vendor_bill_prices(self):
        """
        Check final VAT-inclusive bill line prices against eligible posted bills.
        """
        self.ensure_one()
        return VendorBillFinalUnitPriceChecker(self.env).check(self)

    def _is_eligible_for_vendor_price_history(self):
        """Hook for modules to exclude posted bills from price-check history."""
        self.ensure_one()
        eligible = (
            self.state == 'posted'
            and self.move_type == 'in_invoice'
            and self.payment_state != 'blocked'
        )
        _logger.debug(
            '[VPC_FINAL_UNIT_ELIGIBILITY] bill_id=%s state=%s move_type=%s payment_state=%s eligible=%s',
            self.id,
            self.state,
            self.move_type,
            self.payment_state,
            eligible,
        )
        return eligible

    def action_approve_discrepancy(self):
        """
        Approve price discrepancies for this bill.
        
        This allows the bill to be posted even though there are pricing
        discrepancies compared to historical data.
        
        Returns:
            dict: Action to display notification to user
        
        Raises:
            ValidationError: If no discrepancies exist or already approved
        """
        self.ensure_one()
        _logger.info(f"Approving discrepancies for bill {self.name or 'Unnamed'}")
        
        if not self.discrepancy_ids:
            _logger.error("No price discrepancies to approve")
            raise ValidationError(_('No price discrepancies to approve.'))
            
        if self.discrepancy_approved:
            _logger.warning("Price discrepancies already approved")
            raise ValidationError(_('Price discrepancies already approved.'))
            
        self.write({'discrepancy_approved': True})
        _logger.info(
            '[VPC_HISTORY] discrepancies_approved bill_id=%s approver_id=%s',
            self.id,
            self.env.user.id,
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Price discrepancies have been approved.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_discrepancies(self):
        """
        Open a view showing all price discrepancies for this bill.
        
        Returns:
            dict: Action to open discrepancy list/form view
        """
        self.ensure_one()
        _logger.info(f"Viewing discrepancies for bill {self.name or 'Unnamed'}")
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Price Discrepancies',
            'res_model': 'vendor.price.discrepancy',
            'view_mode': 'list,form',
            'domain': [('bill_id', '=', self.id)],
            'context': {'default_bill_id': self.id}
        }

    def action_view_promised_cost_diffs(self):
        self.ensure_one()
        view = self.env.ref(
            'vendor_price_check.view_account_move_line_promised_cost_diff_list',
            raise_if_not_found=False,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Promised Cost Differences'),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'views': [(view.id, 'list'), (False, 'form')] if view else [(False, 'list'), (False, 'form')],
            'domain': [
                ('move_id', '=', self.id),
                ('display_type', 'not in', ('line_section', 'line_note')),
                ('vendor_promised_cost_vat_incl', '!=', 0.0),
                ('promised_cost_difference_vat_incl', '!=', 0.0),
            ],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
            },
        }

    def action_view_invoice_variance_audits(self):
        self.ensure_one()
        _logger.info(
            '[VPC_VARIANCE] audit_view bill_id=%s bill=%s count=%s user_id=%s',
            self.id,
            self.display_name,
            self.invoice_variance_audit_count,
            self.env.user.id,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice Variance Audits'),
            'res_model': 'vendor.bill.invoice.variance.audit',
            'view_mode': 'list,form',
            'domain': [('bill_id', '=', self.id)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
                'default_bill_id': self.id,
            },
        }

    def action_post(self):
        """
        Override action_post to validate price discrepancies before posting.
        
        Prevents posting vendor bills that have unapproved price discrepancies.
        This ensures pricing anomalies are reviewed before finalizing bills.
        
        Note: Iterates over self to handle batch operations (e.g., POS session closing
        which creates multiple account moves simultaneously).
        
        Returns:
            Result from parent action_post method
            
        Raises:
            ValidationError: If bill has unapproved price discrepancies
        """
        for move in self:
            _logger.info(f"Attempting to post bill {move.name or 'Unnamed'}")
            
            # Check if this move has discrepancies that need approval
            if move.discrepancy_ids and not move.discrepancy_approved:
                _logger.warning(
                    f"Cannot post bill {move.name or 'Unnamed'}: unapproved discrepancies"
                )
                raise ValidationError(_(
                    'Cannot post bill with unapproved price discrepancies. '
                    'Please approve the discrepancies first by clicking the '
                    '"Approve Price Discrepancy" button.'
                ))
        
        # Call parent method to complete posting
        return super(AccountMove, self).action_post()
