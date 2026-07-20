# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ElectricityReading(models.Model):
    _name = 'electricity.reading'
    _description = 'Sub-Meter Electricity Reading Logs'
    _order = 'date desc, id desc'

    meter_id = fields.Many2one(
        'electricity.meter', 
        string='Sub-Meter', 
        required=True, 
        ondelete='cascade'
    )
    partner_id = fields.Many2one(
        'res.partner', 
        related='meter_id.partner_id', 
        string='Customer/Neighbor', 
        store=True, 
        readonly=True
    )
    currency_id = fields.Many2one(
        'res.currency', 
        related='meter_id.company_id.currency_id', 
        string='Currency', 
        readonly=True
    )
    date = fields.Date(
        string='Reading Date', 
        default=fields.Date.context_today, 
        required=True
    )
    previous_reading = fields.Float(
        string='Previous Reading (kWh)', 
        required=True,
        compute='_compute_previous_reading',
        store=True,
        readonly=False
    )
    current_reading = fields.Float(
        string='Current Reading (kWh)', 
        required=True
    )
    units_consumed = fields.Float(
        string='Consumed Units (kWh)', 
        compute='_compute_calculations', 
        store=True
    )
    unit_rate = fields.Float(
        string='Unit Rate (kWh)', 
        required=True,
        default=0.15
    )
    receivable_amount = fields.Monetary(
        string='Receivable Amount (Untaxed)', 
        compute='_compute_calculations', 
        currency_field='currency_id', 
        store=True
    )
    vat_amount = fields.Monetary(
        string='VAT Amount', 
        compute='_compute_calculations', 
        currency_field='currency_id', 
        store=True
    )
    total_amount = fields.Monetary(
        string='Total Billed Amount', 
        compute='_compute_calculations', 
        currency_field='currency_id', 
        store=True
    )
    invoice_id = fields.Many2one(
        'account.move', 
        string='Generated Customer Invoice', 
        readonly=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('measured', 'Measured'),
        ('invoiced', 'Invoiced'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True)

    @api.onchange('meter_id')
    def _onchange_meter_id(self):
        if self.meter_id:
            self.previous_reading = self.meter_id.last_reading
            self.unit_rate = self.meter_id.default_unit_rate
            _logger.debug("Onchange triggered for meter %s: pre-filled prev reading %s and rate %s",
                          self.meter_id.name, self.previous_reading, self.unit_rate)

    @api.depends('meter_id', 'date')
    def _compute_previous_reading(self):
        for record in self:
            if record.meter_id:
                # Search for the latest confirmed or invoiced reading chronologically before this record
                domain = [
                    ('meter_id', '=', record.meter_id.id),
                    ('state', 'in', ('measured', 'invoiced')),
                ]
                if record.id:
                    domain.append(('id', '!=', record.id))
                prev_reading = self.search(domain, order='date desc, id desc', limit=1)
                record.previous_reading = prev_reading.current_reading if prev_reading else 0.0
                _logger.debug("Computed previous reading for meter %s: %s", record.meter_id.name, record.previous_reading)
            else:
                record.previous_reading = 0.0

    @api.depends('current_reading', 'previous_reading', 'unit_rate', 'meter_id.product_id')
    def _compute_calculations(self):
        for rec in self:
            rec.units_consumed = max(0.0, rec.current_reading - rec.previous_reading)
            rec.receivable_amount = rec.units_consumed * rec.unit_rate
            
            # Fetch product config to calculate tax
            product_id = rec.meter_id.product_id.id or int(self.env['ir.config_parameter'].sudo().get_param('electricity_submeter.electricity_product_id') or 0)
            product = self.env['product.product'].browse(product_id) if product_id else False
            
            if product:
                taxes = product.taxes_id.compute_all(
                    rec.receivable_amount, 
                    currency=rec.currency_id, 
                    quantity=1.0, 
                    product=product,
                    partner=rec.partner_id
                )
                rec.vat_amount = sum(t['amount'] for t in taxes['taxes'])
                rec.total_amount = taxes['total_included']
                _logger.debug("Calculated tax for reading %s: untaxed=%s, vat=%s, total=%s",
                              rec.id, rec.receivable_amount, rec.vat_amount, rec.total_amount)
            else:
                rec.vat_amount = 0.0
                rec.total_amount = rec.receivable_amount
                _logger.debug("No product found/configured; set tax to 0.0 for reading %s", rec.id)

    def action_confirm_reading(self):
        for record in self:
            if record.current_reading < record.previous_reading:
                raise UserError(_("Current reading (%s) cannot be lower than the previous reading (%s).") % 
                                (record.current_reading, record.previous_reading))
            record.state = 'measured'
            _logger.info("Confirmed sub-meter reading. ID: %s, Meter: %s, Current: %s",
                         record.id, record.meter_id.name, record.current_reading)

    def action_cancel(self):
        for record in self:
            if record.invoice_id and record.invoice_id.state != 'cancel':
                raise UserError(_("You cannot cancel a reading record that has an active invoice (%s) linked to it. Please cancel or delete the invoice first.") % record.invoice_id.name)
            record.state = 'cancelled'
            _logger.info("Cancelled sub-meter reading log. ID: %s", record.id)

    def action_reset_draft(self):
        for record in self:
            if record.invoice_id:
                raise UserError(_("You cannot reset this record to draft as an invoice (%s) has already been generated.") % record.invoice_id.name)
            record.state = 'draft'
            _logger.info("Reset sub-meter reading to draft. ID: %s", record.id)

    def action_generate_invoice(self):
        self.ensure_one()
        if self.state != 'measured':
            raise UserError(_("You can only generate invoices for readings that are in 'Measured' status."))
        if self.invoice_id:
            raise UserError(_("An invoice has already been generated for this reading log."))

        # Get settings configuration
        company = self.meter_id.company_id
        journal_id = int(self.env['ir.config_parameter'].sudo().get_param('electricity_submeter.electricity_journal_id') or 0)
        account_id = int(self.env['ir.config_parameter'].sudo().get_param('electricity_submeter.electricity_account_id') or 0)
        product_id = self.meter_id.product_id.id or int(self.env['ir.config_parameter'].sudo().get_param('electricity_submeter.electricity_product_id') or 0)

        # Config Validation
        if not journal_id:
            # Fallback search for a standard Sales journal
            journal = self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
            if not journal:
                raise UserError(_("Please configure the default sub-meter invoice journal in Accounting Settings."))
            journal_id = journal.id

        product = self.env['product.product'].browse(product_id)
        if not product:
            raise UserError(_("Please configure the default Electricity Service Product in settings or set it on the sub-meter."))

        # Format line description to show readings transparently on invoice and customer statements
        description = _("Electricity Service - Meter: %s | Period Ending: %s | Readings: %s to %s (Consumed: %s kWh @ %s/%s)") % (
            self.meter_id.name,
            self.date.strftime('%Y-%m-%d'),
            f"{self.previous_reading:,.2f}",
            f"{self.current_reading:,.2f}",
            f"{self.units_consumed:,.2f}",
            f"{self.unit_rate:,.4f}",
            self.currency_id.name or ''
        )

        invoice_line_vals = {
            'name': description,
            'product_id': product.id,
            'quantity': self.units_consumed,
            'price_unit': self.unit_rate,
        }
        if account_id:
            invoice_line_vals['account_id'] = account_id

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'journal_id': journal_id,
            'invoice_date': self.date,
            'company_id': company.id,
            'invoice_line_ids': [(0, 0, invoice_line_vals)],
        }

        _logger.info("Creating invoice for neighbor: %s, Meter: %s, Billed Amount: %s",
                     self.partner_id.name, self.meter_id.name, self.total_amount)
        
        try:
            invoice = self.env['account.move'].create(invoice_vals)
            self.write({
                'invoice_id': invoice.id,
                'state': 'invoiced'
            })
            _logger.info("Invoice created successfully. Invoice ID: %s, Move Code: %s", invoice.id, invoice.name or 'DRAFT')
        except Exception as e:
            _logger.error("Failed to generate Odoo customer invoice. Error: %s", str(e))
            raise UserError(_("Failed to generate Odoo Customer Invoice: %s") % str(e))

        # Return action to open the invoice form view directly for the user
        return {
            'name': _('Customer Invoice'),
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }
