from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_is_zero
import logging

_logger = logging.getLogger(__name__)

class VendorPriceWizard(models.TransientModel):
    _name = 'vendor.price.wizard'
    _description = 'Vendor Price Wizard'

    purchase_id = fields.Many2one('purchase.order', string='Purchase Order', required=True)
    bill_id = fields.Many2one('account.move', string='Vendor Bill')
    line_ids = fields.One2many('vendor.price.wizard.line', 'wizard_id', string='Lines')
    currency_id = fields.Many2one(
        'res.currency',
        related='purchase_id.currency_id',
        readonly=True,
    )
    invoice_total_vat_incl = fields.Monetary(
        string='Invoice Total (VAT Incl.)',
        compute='_compute_invoice_total_vat_incl',
        currency_field='currency_id',
    )
    promised_cost_discrepancy_approved = fields.Boolean(
        string='Promised Cost Discrepancy Approved',
        readonly=True,
    )
    promised_cost_discrepancy_approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
    )
    has_promised_cost_discrepancy = fields.Boolean(
        string='Has Promised Cost Discrepancy',
        compute='_compute_has_promised_cost_discrepancy',
    )

    @api.depends('line_ids.line_total_vat_incl')
    def _compute_invoice_total_vat_incl(self):
        for wizard in self:
            wizard.invoice_total_vat_incl = sum(wizard.line_ids.mapped('line_total_vat_incl'))

    @api.depends(
        'line_ids.vendor_promised_cost_vat_incl',
        'line_ids.unit_price_vat_incl',
        'line_ids.promised_cost_difference_vat_incl',
    )
    def _compute_has_promised_cost_discrepancy(self):
        for wizard in self:
            wizard.has_promised_cost_discrepancy = bool(wizard._get_promised_cost_discrepancy_lines())

    def _get_price_discrepancy_approver(self):
        approver_id = self.env['ir.config_parameter'].sudo().get_param(
            'vendor_price_check.price_check_approver_id',
            default=False,
        )
        return self.env['res.users'].browse(int(approver_id)) if approver_id else self.env['res.users']

    def _get_promised_cost_discrepancy_lines(self):
        self.ensure_one()
        precision = self.currency_id.rounding if self.currency_id else 0.01
        return self.line_ids.filtered(
            lambda line: (
                line.vendor_promised_cost_vat_incl
                and abs(line.promised_cost_difference_vat_incl) > precision
            )
        )

    def action_approve_promised_cost_discrepancy(self):
        self.ensure_one()
        approver = self._get_price_discrepancy_approver()
        if not approver:
            raise ValidationError(_(
                'Please configure a Price Discrepancy Approver in Purchase settings before approving.'
            ))
        if self.env.user != approver:
            raise ValidationError(
                _('Only %(approver)s can approve promised cost discrepancies.')
                % {'approver': approver.display_name}
            )
        if not self._get_promised_cost_discrepancy_lines():
            raise ValidationError(_('There are no promised cost discrepancies to approve.'))

        self.write({
            'promised_cost_discrepancy_approved': True,
            'promised_cost_discrepancy_approved_by_id': self.env.user.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'vendor.price.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def _check_promised_cost_discrepancies(self):
        self.ensure_one()
        discrepancy_lines = self._get_promised_cost_discrepancy_lines()
        if not discrepancy_lines or self.promised_cost_discrepancy_approved:
            return

        approver = self._get_price_discrepancy_approver()
        details = '\n'.join(
            _('- %(product)s: promised %(promised).2f, unit + VAT %(actual).2f, difference %(difference).2f')
            % {
                'product': line.product_id.display_name,
                'promised': line.vendor_promised_cost_vat_incl,
                'actual': line.unit_price_vat_incl,
                'difference': line.promised_cost_difference_vat_incl,
            }
            for line in discrepancy_lines
        )
        approver_message = (
            _('Configured approver: %s') % approver.display_name
            if approver
            else _('No Price Discrepancy Approver is configured in Purchase settings.')
        )
        raise ValidationError(
            _('Vendor promised cost discrepancy detected. Approval is required before creating the bill.\n\n'
              '%(details)s\n\n%(approver_message)s')
            % {
                'details': details,
                'approver_message': approver_message,
            }
        )

    def _get_billable_received_qty(self, purchase_line):
        received_to_bill = max((purchase_line.qty_received or 0.0) - (purchase_line.qty_invoiced or 0.0), 0.0)
        rounding = purchase_line.product_uom.rounding if purchase_line.product_uom else 0.01
        return 0.0 if float_is_zero(received_to_bill, precision_rounding=rounding) else received_to_bill

    def action_create_bill(self):
        self.ensure_one()
        _logger.info(f"Creating/Updating bill for PO {self.purchase_id.name}")

        # Validate all lines before proceeding
        for line in self.line_ids:
            _logger.debug(f"Validating line {line.id}: vendor_price={line.vendor_price}, calculated_subtotal={line.calculated_subtotal}")
            if line.vendor_price is None or line.vendor_price == 0.0:
                raise ValidationError(_("Vendor Price is required and must be a non-zero value for all lines."))

        self._check_promised_cost_discrepancies()

        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': self.purchase_id.partner_id.id,
            'purchase_id': self.purchase_id.id,
            'invoice_origin': self.purchase_id.name,
            'currency_id': self.purchase_id.currency_id.id,
            'invoice_line_ids': [],
        }

        wizard_vendor_prices = {
            line.product_id.id: line.calculated_subtotal
            for line in self.line_ids.filtered(lambda l: l.product_id and l.purchase_line_id)
        }

        for line in self.line_ids.filtered(lambda l: l.product_id and l.purchase_line_id):
            billable_qty = self._get_billable_received_qty(line.purchase_line_id)
            if not billable_qty:
                _logger.info(
                    "Skipping bill line for %s on PO %s: received=%s, already invoiced=%s",
                    line.product_id.display_name,
                    self.purchase_id.name,
                    line.purchase_line_id.qty_received,
                    line.purchase_line_id.qty_invoiced,
                )
                continue
            _logger.info(
                f"📊 {line.product_id.display_name}: "
                f"Vendor={line.vendor_price:.2f} → Calculated={line.calculated_subtotal:.2f} "
                f"(Custom Pricing: {line.use_custom_pricing})"
            )
            price_unit = line.calculated_subtotal  # Use calculated_subtotal directly as tax-exclusive
            bill_line_vals = {
                'product_id': line.product_id.id,
                'quantity': billable_qty,
                'product_uom_id': line.purchase_line_id.product_uom.id,
                'price_unit': price_unit,
                'tax_ids': [(6, 0, line.purchase_line_id.taxes_id.ids)],
                'purchase_line_id': line.purchase_line_id.id,
                'use_custom_pricing': line.use_custom_pricing,
                'net_price': line.calculated_subtotal,
                'applied_discount': line.applied_discount,
                'applied_freight': line.applied_freight,
            }
            bill_vals['invoice_line_ids'].append((0, 0, bill_line_vals))

        if not bill_vals['invoice_line_ids']:
            raise ValidationError(_(
                'There are no validated received quantities left to invoice for this purchase order.'
            ))

        if self.bill_id:
            _logger.info(f"Updating existing bill {self.bill_id.name}")
            self.bill_id.with_context(wizard_vendor_prices=wizard_vendor_prices).write({
                'invoice_line_ids': [(5, 0, 0)] + bill_vals['invoice_line_ids']
            })
            bill = self.bill_id
        else:
            _logger.info("Creating new bill")
            bill = self.env['account.move'].with_context(wizard_vendor_prices=wizard_vendor_prices).create(bill_vals)

        discrepancies = bill._check_vendor_bill_prices()
        if discrepancies:
            _logger.warning(f"⚠️ {len(discrepancies)} discrepancies found")
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': bill.id,
                'target': 'current',
            }

        _logger.info(f"✅ Bill created/updated: ID={bill.id}")
        for line in bill.invoice_line_ids:
            _logger.info(
                f"✅ Line created: {line.product_id.display_name} @ {line.price_unit:.2f} "
                f"(Custom Pricing: {line.use_custom_pricing})"
            )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': bill.id,
            'target': 'current',
        }
