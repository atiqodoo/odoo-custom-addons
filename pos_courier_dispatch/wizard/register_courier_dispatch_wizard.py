# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class RegisterCourierDispatchWizard(models.TransientModel):
    _name = 'register.courier.dispatch.wizard'
    _description = 'Register Courier Dispatch Wizard'

    # ====================
    # BASIC FIELDS
    # ====================
    
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
    )
    
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        help='Select customer for delivery. Leave empty if not applicable.',
    )
    
    # ====================
    # COURIER INFORMATION
    # ====================
    
    courier_company_id = fields.Many2one(
        'courier.company',
        string='Courier Company',
    )
    
    courier_name = fields.Char(
        string='Courier Name',
        required=True,
    )
    
    courier_phone = fields.Char(
        string='Courier Phone',
        required=True,
    )
    
    courier_reference = fields.Char(
        string='Tracking Number',
        help='Courier company tracking/reference number',
    )
    
    vehicle_plate = fields.Char(
        string='Vehicle Plate',
    )
    
    # ====================
    # PAYMENT FIELDS
    # ====================
    
    courier_payment_responsible = fields.Selection([
        ('customer', 'Customer Pays'),
        ('company', 'Company Pays'),
        ('shared', 'Shared Payment'),
    ], string='Payment Responsibility', default='customer', required=True)
    
    courier_fee = fields.Monetary(
        string='Courier Fee',
        currency_field='currency_id',
        default=0.0,
    )
    
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain=[('type', 'in', ['bank', 'cash'])],
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    
    # ====================
    # VAT FIELDS (NEW)
    # ====================
    
    courier_fee_vat_inclusive = fields.Boolean(
        string='Fee is VAT Inclusive',
        default=lambda self: self._get_default_vat_inclusive(),
        help='If true, courier fee includes VAT'
    )
    
    vat_rate = fields.Float(
        string='VAT Rate (%)',
        compute='_compute_vat_rate',
        help='VAT rate for courier services'
    )
    
    courier_fee_net = fields.Monetary(
        string='Fee (Net)',
        currency_field='currency_id',
        compute='_compute_vat_amounts',
        help='Courier fee excluding VAT'
    )
    
    courier_fee_vat = fields.Monetary(
        string='VAT Amount',
        currency_field='currency_id',
        compute='_compute_vat_amounts',
        help='VAT amount on courier fee'
    )
    
    # ====================
    # DELIVERY ADDRESS
    # ====================
    
    use_customer_address = fields.Boolean(
        string='Use Customer Address',
        default=True,
    )
    
    delivery_street = fields.Char(string='Street')
    delivery_street2 = fields.Char(string='Street 2')
    delivery_city = fields.Char(string='City')
    delivery_state_id = fields.Many2one('res.country.state', string='State')
    delivery_zip = fields.Char(string='Zip')
    delivery_country_id = fields.Many2one('res.country', string='Country')
    
    # ====================
    # DOCUMENTATION
    # ====================
    
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'wizard_courier_dispatch_attachment_rel',
        'wizard_id',
        'attachment_id',
        string='Attachments',
    )
    
    delivery_instructions = fields.Text(string='Delivery Instructions')
    notes = fields.Text(string='Notes')
    
    # ====================
    # DISPATCH LINES
    # ====================
    
    line_ids = fields.One2many(
        'register.courier.dispatch.wizard.line',
        'wizard_id',
        string='Items to Dispatch',
    )
    
    # ====================
    # COMPUTED TOTALS
    # ====================
    
    total_quantity = fields.Float(
        string='Total Quantity',
        compute='_compute_totals',
    )
    
    total_value = fields.Monetary(
        string='Total Value',
        currency_field='currency_id',
        compute='_compute_totals',
    )

    # ====================
    # DEFAULT METHODS (VAT)
    # ====================
    
    def _get_default_vat_inclusive(self):
        """Get default VAT inclusive setting from config"""
        vat_inclusive = self.env['ir.config_parameter'].sudo().get_param(
            'pos_courier_dispatch.courier_fee_vat_inclusive',
            'True'
        )
        return vat_inclusive == 'True'

    # ====================
    # COMPUTED METHODS
    # ====================

    @api.depends('line_ids.dispatch_qty', 'line_ids.subtotal')
    def _compute_totals(self):
        """Compute totals"""
        for wizard in self:
            wizard.total_quantity = sum(wizard.line_ids.mapped('dispatch_qty'))
            wizard.total_value = sum(wizard.line_ids.mapped('subtotal'))
            
            _logger.info(
                f"[WIZARD] Totals computed: Qty={wizard.total_quantity}, Value={wizard.total_value}"
            )
    
    # ====================
    # COMPUTED METHODS - VAT (NEW)
    # ====================
    
    @api.depends('currency_id')
    def _compute_vat_rate(self):
        """Get VAT rate from system parameters"""
        for wizard in self:
            vat_rate_param = self.env['ir.config_parameter'].sudo().get_param(
                'pos_courier_dispatch.courier_vat_rate',
                '16.0'
            )
            wizard.vat_rate = float(vat_rate_param)
            
            _logger.info(f"[WIZARD] VAT rate loaded: {wizard.vat_rate}%")
    
    @api.depends('courier_fee', 'vat_rate', 'courier_fee_vat_inclusive')
    def _compute_vat_amounts(self):
        """Calculate net and VAT amounts from courier fee"""
        for wizard in self:
            if not wizard.courier_fee:
                wizard.courier_fee_net = 0.0
                wizard.courier_fee_vat = 0.0
                continue
            
            if wizard.courier_fee_vat_inclusive and wizard.vat_rate > 0:
                # Fee is VAT inclusive - split it
                divisor = 1 + (wizard.vat_rate / 100)
                wizard.courier_fee_net = wizard.courier_fee / divisor
                wizard.courier_fee_vat = wizard.courier_fee - wizard.courier_fee_net
                
                _logger.info(
                    f"[WIZARD] VAT calc (Inclusive): Total={wizard.courier_fee:.2f}, "
                    f"Net={wizard.courier_fee_net:.2f}, VAT={wizard.courier_fee_vat:.2f}"
                )
            else:
                # Fee is net - calculate VAT on top
                wizard.courier_fee_net = wizard.courier_fee
                wizard.courier_fee_vat = wizard.courier_fee * (wizard.vat_rate / 100)
                
                _logger.info(
                    f"[WIZARD] VAT calc (Exclusive): Net={wizard.courier_fee_net:.2f}, "
                    f"VAT={wizard.courier_fee_vat:.2f}"
                )
    
    # ====================
    # ONCHANGE METHODS
    # ====================
    
    @api.onchange('courier_company_id')
    def _onchange_courier_company(self):
        """Auto-fill courier details from company"""
        if self.courier_company_id:
            self.courier_name = self.courier_company_id.name
            self.courier_phone = self.courier_company_id.phone
            if self.courier_company_id.default_journal_id:
                self.payment_journal_id = self.courier_company_id.default_journal_id
            
            _logger.info(f"[WIZARD] Auto-filled from courier company: {self.courier_company_id.name}")
    
    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        """Auto-fill delivery address from selected customer"""
        if self.customer_id and self.use_customer_address:
            self.delivery_street = self.customer_id.street
            self.delivery_street2 = self.customer_id.street2
            self.delivery_city = self.customer_id.city
            self.delivery_state_id = self.customer_id.state_id
            self.delivery_zip = self.customer_id.zip
            self.delivery_country_id = self.customer_id.country_id
            
            _logger.info(f"[WIZARD] Auto-filled address from customer: {self.customer_id.name}")
    
    @api.onchange('use_customer_address')
    def _onchange_use_customer_address(self):
        """Toggle between customer address and custom address"""
        if self.use_customer_address and self.customer_id:
            self.delivery_street = self.customer_id.street
            self.delivery_street2 = self.customer_id.street2
            self.delivery_city = self.customer_id.city
            self.delivery_state_id = self.customer_id.state_id
            self.delivery_zip = self.customer_id.zip
            self.delivery_country_id = self.customer_id.country_id
            
            _logger.info(f"[WIZARD] Address toggled to customer address")
    
    @api.onchange('courier_payment_responsible')
    def _onchange_payment_responsible(self):
        """Load default journal when company/shared pays"""
        if self.courier_payment_responsible in ['company', 'shared']:
            default_journal = self.env['ir.config_parameter'].sudo().get_param(
        'pos_courier_dispatch.courier_payment_journal_id'
        )
            
            if default_journal:
                self.payment_journal_id = int(default_journal)
                _logger.info(f"[WIZARD] Auto-filled payment journal from settings")
    
    # ====================
    # DEFAULT_GET
    # ====================
    
    @api.model
    def default_get(self, fields_list):
        """Load default values from POS order with remaining quantities"""
        _logger.info("=" * 80)
        _logger.info("[WIZARD] === default_get called ===")
        _logger.info("=" * 80)
        
        res = super(RegisterCourierDispatchWizard, self).default_get(fields_list)
        
        pos_order_id = self.env.context.get('default_pos_order_id')
        if not pos_order_id:
            _logger.warning("[WIZARD] No POS order ID in context")
            return res
        
        pos_order = self.env['pos.order'].browse(pos_order_id)
        _logger.info(f"[WIZARD] POS Order: {pos_order.name} (ID: {pos_order.id})")
        _logger.info(f"[WIZARD] Order has {len(pos_order.lines)} lines")
        
        # Set customer from POS order if available
        if pos_order.partner_id:
            res['customer_id'] = pos_order.partner_id.id
            _logger.info(f"[WIZARD] Customer from POS order: {pos_order.partner_id.name}")
        else:
            _logger.info(f"[WIZARD] No customer on POS order")
        
        # Set default address from customer
        if pos_order.partner_id:
            res.update({
                'delivery_street': pos_order.partner_id.street,
                'delivery_street2': pos_order.partner_id.street2,
                'delivery_city': pos_order.partner_id.city,
                'delivery_state_id': pos_order.partner_id.state_id.id if pos_order.partner_id.state_id else False,
                'delivery_zip': pos_order.partner_id.zip,
                'delivery_country_id': pos_order.partner_id.country_id.id if pos_order.partner_id.country_id else False,
            })
            _logger.info(f"[WIZARD] Set default delivery address from customer")
        
        # Get remaining quantities for this order
        remaining_qty = pos_order._get_remaining_quantities()
        
        # Create wizard lines from POS order lines with REMAINING quantities
        line_vals = []
        for idx, pos_line in enumerate(pos_order.lines, 1):
            remaining = remaining_qty.get(pos_line.id, pos_line.qty)
            
            # Only include lines that have remaining quantity
            if remaining > 0.001:  # Use 0.001 for float comparison
                line_data = {
                    'sequence': idx * 10,
                    'pos_order_line_id': pos_line.id,
                    'product_id': pos_line.product_id.id,
                    'ordered_qty': pos_line.qty,
                    'remaining_qty': remaining,
                    'dispatch_qty': remaining,
                    'price_unit': pos_line.price_unit,
                }
                line_vals.append((0, 0, line_data))
                _logger.info(
                    f"[WIZARD] Line {idx}: {pos_line.product_id.name} - "
                    f"Ordered: {pos_line.qty}, Remaining: {remaining}, Will dispatch: {remaining}"
                )
            else:
                _logger.info(
                    f"[WIZARD] Line {idx}: {pos_line.product_id.name} - "
                    f"SKIPPED (fully dispatched)"
                )
        
        res['line_ids'] = line_vals
        _logger.info(f"[WIZARD] Created {len(line_vals)} wizard lines with remaining quantities")
        _logger.info("=" * 80)
        
        return res
    
    # ====================
    # ACTIONS
    # ====================
    
    def action_confirm(self):
        """Create courier dispatch record"""
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("[WIZARD] === action_confirm called ===")
        _logger.info(f"[WIZARD] POS Order: {self.pos_order_id.name}")
        _logger.info(f"[WIZARD] Customer: {self.customer_id.name if self.customer_id else 'None'}")
        _logger.info(f"[WIZARD] Courier: {self.courier_name} ({self.courier_phone})")
        _logger.info(f"[WIZARD] Payment: {self.courier_payment_responsible}")
        _logger.info(f"[WIZARD] Fee: {self.courier_fee:.2f} (VAT Inc: {self.courier_fee_vat_inclusive})")
        _logger.info("=" * 80)
        
        # Validation
        if not self.pos_order_id or not self.pos_order_id.lines:
            _logger.error("[WIZARD] POS order has no lines")
            raise UserError(_('POS order has no lines.'))
        
        if not self.courier_name or not self.courier_phone:
            _logger.error("[WIZARD] Missing courier details")
            raise UserError(_('Courier name and phone are required.'))
        
        if self.courier_payment_responsible in ['company', 'shared']:
            if not self.payment_journal_id:
                _logger.error("[WIZARD] Payment journal required but not set")
                raise UserError(_('Payment journal is required when company pays courier fee.'))
            if self.courier_fee <= 0:
                _logger.error("[WIZARD] Courier fee must be > 0 when company pays")
                raise UserError(_('Courier fee must be greater than zero when company pays.'))
        
        # Reload wizard lines to get fresh data
        _logger.info("[WIZARD] Reloading wizard line data...")
        self.line_ids.invalidate_recordset()
        
        # Build dispatch quantities map
        dispatch_qty_map = {}
        for wizard_line in self.line_ids:
            if wizard_line.dispatch_qty > 0:
                dispatch_qty_map[wizard_line.sequence] = wizard_line.dispatch_qty
                _logger.info(
                    f"[WIZARD] Will dispatch: {wizard_line.product_id.name}, "
                    f"Qty: {wizard_line.dispatch_qty}"
                )
        
        if not dispatch_qty_map:
            _logger.error("[WIZARD] No dispatch quantities specified")
            raise UserError(_('Please specify quantities to dispatch.'))
        
        _logger.info(f"[WIZARD] Total lines to dispatch: {len(dispatch_qty_map)}")
        
        # Prepare dispatch lines from POS order lines
        dispatch_lines = []
        for idx, pos_line in enumerate(self.pos_order_id.lines, 1):
            sequence = idx * 10
            dispatch_qty = dispatch_qty_map.get(sequence, 0.0)
            
            if dispatch_qty <= 0:
                _logger.info(f"[WIZARD] Skipping POS line {idx}: zero dispatch quantity")
                continue
            
            line_vals = {
                'sequence': sequence,
                'pos_order_line_id': pos_line.id,
                'product_id': pos_line.product_id.id,
                'quantity': dispatch_qty,
                'ordered_qty': pos_line.qty,
                'price_unit': pos_line.price_unit,
                'weight': pos_line.product_id.weight * dispatch_qty,
            }
            dispatch_lines.append((0, 0, line_vals))
            
            _logger.info(
                f"[WIZARD] Added dispatch line: {pos_line.product_id.name}, "
                f"Qty: {dispatch_qty}, Price: {pos_line.price_unit}"
            )
        
        # Create dispatch record
        dispatch_vals = {
            'pos_order_id': self.pos_order_id.id,
            'customer_id': self.customer_id.id if self.customer_id else False,
            'courier_company_id': self.courier_company_id.id if self.courier_company_id else False,
            'courier_name': self.courier_name,
            'courier_phone': self.courier_phone,
            'courier_reference': self.courier_reference,
            'vehicle_plate': self.vehicle_plate,
            'courier_payment_responsible': self.courier_payment_responsible,
            'courier_fee': self.courier_fee,
            'courier_fee_vat_inclusive': self.courier_fee_vat_inclusive,
            'payment_journal_id': self.payment_journal_id.id if self.payment_journal_id else False,
            'delivery_street': self.delivery_street,
            'delivery_street2': self.delivery_street2,
            'delivery_city': self.delivery_city,
            'delivery_state_id': self.delivery_state_id.id if self.delivery_state_id else False,
            'delivery_zip': self.delivery_zip,
            'delivery_country_id': self.delivery_country_id.id if self.delivery_country_id else False,
            'delivery_instructions': self.delivery_instructions,
            'notes': self.notes,
            'line_ids': dispatch_lines,
        }
        
        _logger.info("[WIZARD] Creating courier dispatch record...")
        dispatch = self.env['courier.dispatch'].create(dispatch_vals)
        _logger.info(f"[WIZARD] Dispatch created: {dispatch.name}")
        
        # Link attachments
        if self.attachment_ids:
            _logger.info(f"[WIZARD] Linking {len(self.attachment_ids)} attachments")
            self.attachment_ids.write({
                'res_model': 'courier.dispatch',
                'res_id': dispatch.id,
            })
        
        # Automatically dispatch (create stock moves and payment entry)
        _logger.info("[WIZARD] Triggering action_dispatch...")
        dispatch.action_dispatch()
        
        _logger.info("[WIZARD] === action_confirm completed successfully ===")
        _logger.info("=" * 80)
        
        # Return action to view created dispatch
        return {
            'name': _('Courier Dispatch'),
            'type': 'ir.actions.act_window',
            'res_model': 'courier.dispatch',
            'view_mode': 'form',
            'res_id': dispatch.id,
            'target': 'current',
        }


class RegisterCourierDispatchWizardLine(models.TransientModel):
    _name = 'register.courier.dispatch.wizard.line'
    _description = 'Register Courier Dispatch Wizard Line'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    
    wizard_id = fields.Many2one(
        'register.courier.dispatch.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    
    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        required=False,
        readonly=False,
    )
    
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=False,
        readonly=False,
    )
    
    ordered_qty = fields.Float(
        string='Ordered Qty',
        readonly=False,
        digits='Product Unit of Measure',
        help='Original quantity from POS order'
    )
    
    remaining_qty = fields.Float(
        string='Remaining Qty',
        readonly=True,
        digits='Product Unit of Measure',
        help='Quantity available for dispatch (not yet dispatched)',
    )
    
    dispatch_qty = fields.Float(
        string='Dispatch Qty',
        required=True,
        default=0.0,
        digits='Product Unit of Measure',
        help='Quantity to dispatch now',
    )
    
    price_unit = fields.Float(
        string='Unit Price',
        readonly=False,
        digits='Product Price',
    )
    
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        digits='Product Price',
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='wizard_id.currency_id',
        readonly=True,
    )

    @api.depends('dispatch_qty', 'price_unit')
    def _compute_subtotal(self):
        """Calculate line subtotal"""
        for line in self:
            line.subtotal = line.dispatch_qty * line.price_unit
    
    @api.constrains('dispatch_qty', 'remaining_qty')
    def _check_dispatch_qty(self):
        """Validate dispatch quantity against remaining quantity"""
        for line in self:
            # Skip validation if remaining_qty not set yet (form still loading)
            if not line.remaining_qty or line.remaining_qty == 0:
                continue
            
            # Validate: dispatch cannot exceed remaining
            if line.dispatch_qty > line.remaining_qty:
                _logger.error(
                    f"[WIZARD LINE] Validation failed: dispatch_qty ({line.dispatch_qty}) > "
                    f"remaining_qty ({line.remaining_qty}) for {line.product_id.display_name}"
                )
                raise ValidationError(_(
                    'Dispatch quantity (%.2f) cannot exceed remaining quantity (%.2f) for %s'
                ) % (line.dispatch_qty, line.remaining_qty, line.product_id.display_name or 'product'))
            
            # Validate: dispatch cannot be negative
            if line.dispatch_qty < 0:
                _logger.error(f"[WIZARD LINE] Validation failed: negative dispatch_qty for {line.product_id.display_name}")
                raise ValidationError(_('Dispatch quantity cannot be negative'))