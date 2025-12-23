# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class CourierDispatch(models.Model):
    _name = 'courier.dispatch'
    _description = 'Courier Dispatch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'dispatch_date desc, id desc'
    _rec_name = 'name'

    # ====================
    # BASIC FIELDS
    # ====================
    
    name = fields.Char(
        string='Dispatch Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New')
    )
    
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        ondelete='restrict',
        tracking=True,
    )
    
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=False,
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
    )
    
    # ====================
    # DATE FIELDS
    # ====================
    
    dispatch_date = fields.Datetime(
        string='Dispatch Date',
        default=fields.Datetime.now,
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    delivery_date = fields.Datetime(
        string='Delivery Date',
        readonly=True,
        tracking=True,
    )
    
    confirmation_date = fields.Datetime(
        string='Confirmation Date',
        readonly=True,
        tracking=True,
    )
    
    # ====================
    # COURIER INFORMATION
    # ====================
    
    courier_company_id = fields.Many2one(
        'courier.company',
        string='Courier Company',
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    courier_name = fields.Char(
        string='Courier Name',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    courier_phone = fields.Char(
        string='Courier Phone',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    courier_reference = fields.Char(
        string='Tracking Number',
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
        help='Courier company tracking/reference number',
    )
    
    vehicle_plate = fields.Char(
        string='Vehicle Plate',
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    # ====================
    # PAYMENT FIELDS
    # ====================
    
    courier_payment_responsible = fields.Selection([
        ('customer', 'Customer Pays'),
        ('company', 'Company Pays'),
        ('shared', 'Shared Payment'),
    ], string='Payment Responsibility', default='customer', required=True,
        readonly=True, states={'draft': [('readonly', False)]}, tracking=True)
    
    courier_fee = fields.Monetary(
        string='Courier Fee',
        currency_field='currency_id',
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    
    company_fee_portion = fields.Monetary(
        string='Company Portion',
        currency_field='currency_id',
        compute='_compute_company_fee_portion',
        store=True,
        help='Amount paid by company (full for company, half for shared, zero for customer)',
    )
    
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        readonly=True,
        states={'draft': [('readonly', False)]},
        domain=[('type', 'in', ['bank', 'cash'])],
        tracking=True,
    )
    
    payment_move_id = fields.Many2one(
        'account.move',
        string='Payment Journal Entry',
        readonly=True,
        copy=False,
    )
    
    # ====================
    # VAT FIELDS (NEW)
    # ====================
    
    courier_fee_vat_inclusive = fields.Boolean(
        string='Fee is VAT Inclusive',
        default=lambda self: self._get_default_vat_inclusive(),
        readonly=True,
        states={'draft': [('readonly', False)]},
        help='If true, courier fee includes VAT'
    )
    
    vat_rate = fields.Float(
        string='VAT Rate (%)',
        compute='_compute_vat_rate',
        store=True,
        help='VAT rate for courier services'
    )
    
    courier_fee_net = fields.Monetary(
        string='Courier Fee (Net)',
        currency_field='currency_id',
        compute='_compute_vat_amounts',
        store=True,
        help='Courier fee excluding VAT'
    )
    
    courier_fee_vat = fields.Monetary(
        string='VAT Amount',
        currency_field='currency_id',
        compute='_compute_vat_amounts',
        store=True,
        help='VAT amount on courier fee'
    )
    
    company_fee_net = fields.Monetary(
        string='Company Portion (Net)',
        currency_field='currency_id',
        compute='_compute_company_vat_amounts',
        store=True,
    )
    
    company_fee_vat = fields.Monetary(
        string='Company Portion (VAT)',
        currency_field='currency_id',
        compute='_compute_company_vat_amounts',
        store=True,
    )
    
    # ====================
    # DELIVERY ADDRESS
    # ====================
    
    delivery_street = fields.Char(string='Street')
    delivery_street2 = fields.Char(string='Street 2')
    delivery_city = fields.Char(string='City')
    delivery_state_id = fields.Many2one('res.country.state', string='State')
    delivery_zip = fields.Char(string='Zip')
    delivery_country_id = fields.Many2one('res.country', string='Country')
    
    # ====================
    # DOCUMENTATION
    # ====================
    
    notes = fields.Text(string='Notes')
    delivery_instructions = fields.Text(string='Delivery Instructions')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'courier_dispatch_attachment_rel',
        'dispatch_id',
        'attachment_id',
        string='Attachments',
    )
    
    # ====================
    # RELATIONS
    # ====================
    
    line_ids = fields.One2many(
        'courier.dispatch.line',
        'dispatch_id',
        string='Dispatch Lines',
        readonly=True,
        states={'draft': [('readonly', False)]},
    )
    
    stock_move_ids = fields.One2many(
        'stock.move',
        'courier_dispatch_id',
        string='Stock Moves',
        readonly=True,
    )
    
    # ====================
    # COMPUTED FIELDS
    # ====================
    
    total_quantity = fields.Float(
        string='Total Quantity',
        compute='_compute_totals',
        store=True,
    )
    
    total_weight = fields.Float(
        string='Total Weight (kg)',
        compute='_compute_totals',
        store=True,
    )
    
    total_value = fields.Monetary(
        string='Total Value',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )

    # ====================
    # DEFAULT METHODS
    # ====================
    
    def _get_default_vat_inclusive(self):
        """Get default VAT inclusive setting from config"""
        vat_inclusive = self.env['ir.config_parameter'].sudo().get_param(
            'pos_courier_dispatch.courier_fee_vat_inclusive',
            'True'
        )
        return vat_inclusive == 'True'

    # ====================
    # COMPUTED METHODS - TOTALS
    # ====================

    @api.depends('line_ids.quantity', 'line_ids.weight', 'line_ids.subtotal')
    def _compute_totals(self):
        """Compute total quantity, weight, and value"""
        for dispatch in self:
            dispatch.total_quantity = sum(dispatch.line_ids.mapped('quantity'))
            dispatch.total_weight = sum(dispatch.line_ids.mapped('weight'))
            dispatch.total_value = sum(dispatch.line_ids.mapped('subtotal'))
            
            _logger.info(
                f"[COURIER_DISPATCH] {dispatch.name or 'New'} - Totals computed: "
                f"Qty={dispatch.total_quantity}, Weight={dispatch.total_weight}, Value={dispatch.total_value}"
            )
    
    @api.depends('courier_payment_responsible', 'courier_fee')
    def _compute_company_fee_portion(self):
        """Calculate company's portion of courier fee"""
        for dispatch in self:
            if dispatch.courier_payment_responsible == 'company':
                dispatch.company_fee_portion = dispatch.courier_fee
            elif dispatch.courier_payment_responsible == 'shared':
                dispatch.company_fee_portion = dispatch.courier_fee / 2
            else:
                dispatch.company_fee_portion = 0.0
            
            _logger.info(
                f"[COURIER_DISPATCH] {dispatch.name or 'New'} - Company portion: "
                f"{dispatch.company_fee_portion} (Responsibility: {dispatch.courier_payment_responsible})"
            )
    
    # ====================
    # COMPUTED METHODS - VAT (NEW)
    # ====================
    
    @api.depends('company_id')
    def _compute_vat_rate(self):
        """Get VAT rate from system parameters"""
        for dispatch in self:
            vat_rate_param = self.env['ir.config_parameter'].sudo().get_param(
                'pos_courier_dispatch.courier_vat_rate',
                '16.0'
            )
            dispatch.vat_rate = float(vat_rate_param)
            
            _logger.info(
                f"[COURIER_DISPATCH] {dispatch.name or 'New'} - VAT rate loaded: {dispatch.vat_rate}%"
            )
    
    @api.depends('courier_fee', 'vat_rate', 'courier_fee_vat_inclusive')
    def _compute_vat_amounts(self):
        """Calculate net and VAT amounts from courier fee"""
        for dispatch in self:
            if not dispatch.courier_fee:
                dispatch.courier_fee_net = 0.0
                dispatch.courier_fee_vat = 0.0
                _logger.info(f"[COURIER_DISPATCH] {dispatch.name or 'New'} - No courier fee, VAT amounts = 0")
                continue
            
            if dispatch.courier_fee_vat_inclusive and dispatch.vat_rate > 0:
                # Fee is VAT inclusive - split it
                divisor = 1 + (dispatch.vat_rate / 100)
                dispatch.courier_fee_net = dispatch.courier_fee / divisor
                dispatch.courier_fee_vat = dispatch.courier_fee - dispatch.courier_fee_net
                
                _logger.info(
                    f"[COURIER_DISPATCH] {dispatch.name or 'New'} - VAT calc (Inclusive): "
                    f"Total={dispatch.courier_fee:.2f}, Divisor={divisor:.4f}, "
                    f"Net={dispatch.courier_fee_net:.2f}, VAT={dispatch.courier_fee_vat:.2f}"
                )
            else:
                # Fee is net - calculate VAT on top
                dispatch.courier_fee_net = dispatch.courier_fee
                dispatch.courier_fee_vat = dispatch.courier_fee * (dispatch.vat_rate / 100)
                
                _logger.info(
                    f"[COURIER_DISPATCH] {dispatch.name or 'New'} - VAT calc (Exclusive): "
                    f"Net={dispatch.courier_fee_net:.2f}, VAT={dispatch.courier_fee_vat:.2f}"
                )
    
    @api.depends('courier_payment_responsible', 'company_fee_portion', 'courier_fee_net', 'courier_fee_vat')
    def _compute_company_vat_amounts(self):
        """Calculate net and VAT for company's portion"""
        for dispatch in self:
            if dispatch.courier_payment_responsible == 'customer':
                dispatch.company_fee_net = 0.0
                dispatch.company_fee_vat = 0.0
            elif dispatch.courier_payment_responsible == 'company':
                dispatch.company_fee_net = dispatch.courier_fee_net
                dispatch.company_fee_vat = dispatch.courier_fee_vat
            elif dispatch.courier_payment_responsible == 'shared':
                # 50/50 split of both net and VAT
                dispatch.company_fee_net = dispatch.courier_fee_net / 2
                dispatch.company_fee_vat = dispatch.courier_fee_vat / 2
            else:
                dispatch.company_fee_net = 0.0
                dispatch.company_fee_vat = 0.0
            
            _logger.info(
                f"[COURIER_DISPATCH] {dispatch.name or 'New'} - Company VAT split: "
                f"Responsibility={dispatch.courier_payment_responsible}, "
                f"Net={dispatch.company_fee_net:.2f}, VAT={dispatch.company_fee_vat:.2f}, "
                f"Total={dispatch.company_fee_portion:.2f}"
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
            
            _logger.info(
                f"[COURIER_DISPATCH] Auto-filled from courier company: {self.courier_company_id.name}"
            )
    
    @api.onchange('customer_id')
    def _onchange_customer(self):
        """Auto-fill delivery address from customer"""
        if self.customer_id:
            self.delivery_street = self.customer_id.street
            self.delivery_street2 = self.customer_id.street2
            self.delivery_city = self.customer_id.city
            self.delivery_state_id = self.customer_id.state_id
            self.delivery_zip = self.customer_id.zip
            self.delivery_country_id = self.customer_id.country_id
            
            _logger.info(
                f"[COURIER_DISPATCH] Auto-filled delivery address from customer: {self.customer_id.name}"
            )
    
    # ====================
    # VALIDATION (NEW - VAT)
    # ====================
    
    @api.constrains('courier_payment_responsible', 'courier_fee', 'payment_journal_id')
    def _check_vat_account_configured(self):
        """Ensure VAT account is configured when company pays"""
        for dispatch in self:
            if dispatch.courier_payment_responsible in ['company', 'shared'] and dispatch.courier_fee > 0:
                vat_account_param = self.env['ir.config_parameter'].sudo().get_param(
                    'pos_courier_dispatch.courier_vat_account_id'
                )
                if not vat_account_param:
                    _logger.error(
                        f"[COURIER_DISPATCH] VAT account not configured for dispatch {dispatch.name}"
                    )
                    raise ValidationError(_(
                        'VAT Input account must be configured before creating '
                        'company-paid courier dispatches.\n\n'
                        'Please go to: Settings → Point of Sale → Courier Dispatch\n'
                        'and configure the VAT Input Account.'
                    ))
                
                _logger.info(
                    f"[COURIER_DISPATCH] {dispatch.name} - VAT account validation passed"
                )
    
    # ====================
    # CREATE/WRITE METHODS
    # ====================
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to assign sequence"""
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('courier.dispatch') or _('New')
        
        dispatches = super(CourierDispatch, self).create(vals_list)
        
        for dispatch in dispatches:
            _logger.info(
                f"[COURIER_DISPATCH] Created dispatch {dispatch.name} for POS order {dispatch.pos_order_id.name}"
            )
        
        return dispatches
    
    # ====================
    # ACTION METHODS
    # ====================
    
    def action_dispatch(self):
        """Mark dispatch as in transit and create stock moves"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] === Dispatching {self.name} ===")
        
        if not self.line_ids:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - No dispatch lines found")
            raise UserError(_('Cannot dispatch without any items. Please add dispatch lines.'))
        
        if not self.courier_name or not self.courier_phone:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - Missing courier details")
            raise UserError(_('Courier name and phone are required before dispatching.'))
        
        # Create stock moves
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Creating stock moves...")
        self._create_stock_moves()
        
        # Create accounting entry if company pays
        if self.courier_payment_responsible in ['company', 'shared'] and self.company_fee_portion > 0:
            _logger.info(f"[COURIER_DISPATCH] {self.name} - Creating payment entry...")
            self._create_payment_entry()
        else:
            _logger.info(f"[COURIER_DISPATCH] {self.name} - No payment entry needed (customer pays)")
        
        # Update state
        self.write({
            'state': 'in_transit',
            'dispatch_date': fields.Datetime.now(),
        })
        
        # Post message
        self.message_post(
            body=_('Courier dispatch initiated. Items sent with %s (Phone: %s)') % (
                self.courier_name,
                self.courier_phone
            ),
            subject=_('Dispatch Started'),
        )
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} marked as in_transit - Dispatch complete")
        
        return True
    
    def action_mark_delivered(self):
        """Mark dispatch as delivered"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] Marking {self.name} as delivered")
        
        self.write({
            'state': 'delivered',
            'delivery_date': fields.Datetime.now(),
        })
        
        self.message_post(
            body=_('Dispatch delivered to customer'),
            subject=_('Delivered'),
        )
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} marked as delivered")
        
        return True
    
    def action_confirm_receipt(self):
        """Customer confirms receipt - final state"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] Customer confirmed receipt of {self.name}")
        
        self.write({
            'state': 'confirmed',
            'confirmation_date': fields.Datetime.now(),
        })
        
        self.message_post(
            body=_('Customer confirmed receipt of goods in good condition'),
            subject=_('Receipt Confirmed'),
        )
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} marked as confirmed")
        
        return True
    
    def action_cancel(self):
        """Cancel dispatch and reverse actions"""
        for dispatch in self:
            _logger.info(f"[COURIER_DISPATCH] === Cancelling {dispatch.name} ===")
            
            if dispatch.state not in ['draft', 'in_transit']:
                _logger.error(f"[COURIER_DISPATCH] {dispatch.name} - Cannot cancel from state: {dispatch.state}")
                raise UserError(_('Cannot cancel a dispatch that has been delivered or confirmed.'))
            
            # Reverse stock moves
            if dispatch.stock_move_ids:
                _logger.info(f"[COURIER_DISPATCH] {dispatch.name} - Reversing {len(dispatch.stock_move_ids)} stock moves")
                dispatch.stock_move_ids._action_cancel()
            
            # Reverse payment entry
            if dispatch.payment_move_id and dispatch.payment_move_id.state == 'posted':
                _logger.info(f"[COURIER_DISPATCH] {dispatch.name} - Reversing payment entry {dispatch.payment_move_id.name}")
                # Create reversal
                reversal_wizard = self.env['account.move.reversal'].create({
                    'move_ids': [(4, dispatch.payment_move_id.id)],
                    'reason': f'Cancelled courier dispatch {dispatch.name}',
                    'journal_id': dispatch.payment_move_id.journal_id.id,
                })
                reversal_wizard.refund_moves()
                _logger.info(f"[COURIER_DISPATCH] {dispatch.name} - Payment reversal created")
            
            dispatch.write({'state': 'cancelled'})
            
            dispatch.message_post(
                body=_('Courier dispatch cancelled'),
                subject=_('Cancelled'),
            )
            
            _logger.info(f"[COURIER_DISPATCH] {dispatch.name} cancelled successfully")
    
    # ====================
    # PRIVATE METHODS
    # ====================
    
    def _create_stock_moves(self):
        """Create stock moves from Shop to Courier Transit location"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] === Creating stock moves for {self.name} ===")
        
        # Get locations
        courier_location = self.env.ref('pos_courier_dispatch.stock_location_courier_transit', raise_if_not_found=False)
        if not courier_location:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - Courier Transit location not found")
            raise UserError(_('Courier Transit location not found. Please check module installation.'))
        
        # Get source location from POS config
        source_location = self.pos_order_id.config_id.picking_type_id.default_location_src_id
        if not source_location:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - Cannot determine source location from POS config")
            raise UserError(_('Cannot determine source location from POS configuration.'))
        
        _logger.info(
            f"[COURIER_DISPATCH] {self.name} - Moving stock: "
            f"{source_location.name} → {courier_location.name}"
        )
        
        stock_move_obj = self.env['stock.move']
        move_count = 0
        
        for line in self.line_ids:
            if line.quantity <= 0:
                _logger.warning(f"[COURIER_DISPATCH] {self.name} - Skipping line with zero quantity: {line.product_id.name}")
                continue
            
            move_vals = {
                'name': f'{self.name}: {line.product_id.display_name}',
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
                'product_uom': line.product_id.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': courier_location.id,
                'courier_dispatch_id': self.id,
                'origin': self.name,
                'company_id': self.company_id.id,
            }
            
            move = stock_move_obj.create(move_vals)
            move._action_confirm()
            move._action_assign()
            move._action_done()
            move_count += 1
            
            _logger.info(
                f"[COURIER_DISPATCH] {self.name} - Stock move created: "
                f"{line.product_id.name}, Qty: {line.quantity}, Move ID: {move.id}"
            )
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Created {move_count} stock moves successfully")
    
    def _create_payment_entry(self):
        """Create journal entry for company-paid courier fee with VAT split"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] === Creating payment entry for {self.name} ===")
        
        if not self.payment_journal_id:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - Payment journal not set")
            raise UserError(_('Payment journal is required when company pays courier fee.'))
        
        if self.company_fee_portion <= 0:
            _logger.warning(f"[COURIER_DISPATCH] {self.name} - No company portion to pay, skipping entry")
            return
        
        _logger.info(
            f"[COURIER_DISPATCH] {self.name} - Payment breakdown: "
            f"Total={self.company_fee_portion:.2f}, "
            f"Net={self.company_fee_net:.2f}, "
            f"VAT={self.company_fee_vat:.2f}, "
            f"VAT Rate={self.vat_rate}%"
        )
        
        # Get COGS account
        cogs_account_param = self.env['ir.config_parameter'].sudo().get_param(
            'pos_courier_dispatch.courier_cogs_account_id'
        )
        if not cogs_account_param:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - COGS account not configured")
            raise UserError(_(
                'Courier COGS account not configured.\n\n'
                'Please go to: Settings → Point of Sale → Courier Dispatch\n'
                'and configure the Courier COGS Account.'
            ))
        
        cogs_account = self.env['account.account'].browse(int(cogs_account_param))
        if not cogs_account.exists():
            _logger.error(f"[COURIER_DISPATCH] {self.name} - COGS account ID {cogs_account_param} does not exist")
            raise UserError(_('Configured COGS account (ID: %s) does not exist.') % cogs_account_param)
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Using COGS account: {cogs_account.code} - {cogs_account.name}")
        
        # Get VAT account
        vat_account_param = self.env['ir.config_parameter'].sudo().get_param(
            'pos_courier_dispatch.courier_vat_account_id'
        )
        if not vat_account_param:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - VAT account not configured")
            raise UserError(_(
                'Courier VAT Input account not configured.\n\n'
                'Please go to: Settings → Point of Sale → Courier Dispatch\n'
                'and configure the VAT Input Account.'
            ))
        
        vat_account = self.env['account.account'].browse(int(vat_account_param))
        if not vat_account.exists():
            _logger.error(f"[COURIER_DISPATCH] {self.name} - VAT account ID {vat_account_param} does not exist")
            raise UserError(_('Configured VAT account (ID: %s) does not exist.') % vat_account_param)
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Using VAT account: {vat_account.code} - {vat_account.name}")
        
        # Get payment account from journal
        payment_account = self.payment_journal_id.default_account_id
        if not payment_account:
            _logger.error(f"[COURIER_DISPATCH] {self.name} - Payment journal has no default account")
            raise UserError(_('Payment journal %s has no default account configured.') % self.payment_journal_id.name)
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Using payment account: {payment_account.code} - {payment_account.name}")
        
        # Build journal entry lines
        line_vals = []
        
        # Line 1: Debit COGS (Net Amount)
        if self.company_fee_net > 0:
            line_vals.append((0, 0, {
                'account_id': cogs_account.id,
                'name': f'Courier fee (Net): {self.name}',
                'debit': self.company_fee_net,
                'credit': 0.0,
            }))
            _logger.info(f"[COURIER_DISPATCH] {self.name} - Entry line: Debit COGS {self.company_fee_net:.2f}")
        
        # Line 2: Debit VAT Input (VAT Amount)
        if self.company_fee_vat > 0:
            line_vals.append((0, 0, {
                'account_id': vat_account.id,
                'name': f'VAT on courier fee: {self.name}',
                'debit': self.company_fee_vat,
                'credit': 0.0,
            }))
            _logger.info(f"[COURIER_DISPATCH] {self.name} - Entry line: Debit VAT Input {self.company_fee_vat:.2f}")
        
        # Line 3: Credit Payment Account (Total)
        line_vals.append((0, 0, {
            'account_id': payment_account.id,
            'name': f'Courier payment: {self.name}',
            'debit': 0.0,
            'credit': self.company_fee_portion,
        }))
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Entry line: Credit Payment {self.company_fee_portion:.2f}")
        
        # Verify debit = credit
        total_debit = self.company_fee_net + self.company_fee_vat
        total_credit = self.company_fee_portion
        if abs(total_debit - total_credit) > 0.01:  # Allow 1 cent rounding difference
            _logger.error(
                f"[COURIER_DISPATCH] {self.name} - Accounting entry unbalanced! "
                f"Debit={total_debit:.2f}, Credit={total_credit:.2f}"
            )
            raise UserError(_(
                'Accounting entry is unbalanced. Please check VAT calculations.\n'
                'Debit: %.2f, Credit: %.2f'
            ) % (total_debit, total_credit))
        
        # Create journal entry
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': self.name,
            'line_ids': line_vals,
        }
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} - Creating journal entry...")
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        
        self.payment_move_id = move.id
        
        _logger.info(
            f"[COURIER_DISPATCH] {self.name} - Payment entry created successfully: {move.name} "
            f"(Net: {self.company_fee_net:.2f}, VAT: {self.company_fee_vat:.2f}, Total: {self.company_fee_portion:.2f})"
        )


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    courier_dispatch_id = fields.Many2one(
        'courier.dispatch',
        string='Courier Dispatch',
        ondelete='cascade',
        index=True,
    )