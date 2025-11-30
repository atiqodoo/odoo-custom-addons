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

    # Basic Information
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
        required=False,  # Not required - can dispatch without customer
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
    
    # Dates
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
    
    # Courier Information
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
    
    # Payment Information
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
    
    # Delivery Address
    delivery_street = fields.Char(string='Street')
    delivery_street2 = fields.Char(string='Street 2')
    delivery_city = fields.Char(string='City')
    delivery_state_id = fields.Many2one('res.country.state', string='State')
    delivery_zip = fields.Char(string='Zip')
    delivery_country_id = fields.Many2one('res.country', string='Country')
    
    # Documentation
    notes = fields.Text(string='Notes')
    delivery_instructions = fields.Text(string='Delivery Instructions')
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'courier_dispatch_attachment_rel',
        'dispatch_id',
        'attachment_id',
        string='Attachments',
    )
    
    # Relations
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
    
    # Computed Fields
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

    @api.depends('line_ids.quantity', 'line_ids.weight', 'line_ids.subtotal')
    def _compute_totals(self):
        """Compute total quantity, weight, and value"""
        for dispatch in self:
            dispatch.total_quantity = sum(dispatch.line_ids.mapped('quantity'))
            dispatch.total_weight = sum(dispatch.line_ids.mapped('weight'))
            dispatch.total_value = sum(dispatch.line_ids.mapped('subtotal'))
    
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
    
    @api.onchange('courier_company_id')
    def _onchange_courier_company(self):
        """Auto-fill courier details from company"""
        if self.courier_company_id:
            self.courier_name = self.courier_company_id.name
            self.courier_phone = self.courier_company_id.phone
            if self.courier_company_id.default_journal_id:
                self.payment_journal_id = self.courier_company_id.default_journal_id
    
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
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create to assign sequence"""
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('courier.dispatch') or _('New')
        
        dispatches = super(CourierDispatch, self).create(vals_list)
        
        for dispatch in dispatches:
            _logger.info(f"[COURIER_DISPATCH] Created dispatch {dispatch.name} for POS order {dispatch.pos_order_id.name}")
        
        return dispatches
    
    def action_dispatch(self):
        """Mark dispatch as in transit and create stock moves"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] Dispatching {self.name}")
        
        if not self.line_ids:
            raise UserError(_('Cannot dispatch without any items. Please add dispatch lines.'))
        
        if not self.courier_name or not self.courier_phone:
            raise UserError(_('Courier name and phone are required before dispatching.'))
        
        # Create stock moves
        self._create_stock_moves()
        
        # Create accounting entry if company pays
        if self.courier_payment_responsible in ['company', 'shared'] and self.company_fee_portion > 0:
            self._create_payment_entry()
        
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
        
        _logger.info(f"[COURIER_DISPATCH] {self.name} marked as in_transit")
        
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
        
        return True
    
    def action_cancel(self):
        """Cancel dispatch and reverse actions"""
        for dispatch in self:
            _logger.info(f"[COURIER_DISPATCH] Cancelling {dispatch.name}")
            
            if dispatch.state not in ['draft', 'in_transit']:
                raise UserError(_('Cannot cancel a dispatch that has been delivered or confirmed.'))
            
            # Reverse stock moves
            if dispatch.stock_move_ids:
                dispatch.stock_move_ids._action_cancel()
            
            # Reverse payment entry
            if dispatch.payment_move_id and dispatch.payment_move_id.state == 'posted':
                # Create reversal
                reversal_wizard = self.env['account.move.reversal'].create({
                    'move_ids': [(4, dispatch.payment_move_id.id)],
                    'reason': f'Cancelled courier dispatch {dispatch.name}',
                    'journal_id': dispatch.payment_move_id.journal_id.id,
                })
                reversal_wizard.refund_moves()
            
            dispatch.write({'state': 'cancelled'})
            
            dispatch.message_post(
                body=_('Courier dispatch cancelled'),
                subject=_('Cancelled'),
            )
    
    def _create_stock_moves(self):
        """Create stock moves from Shop to Courier Transit location"""
        self.ensure_one()
        
        _logger.info(f"[COURIER_DISPATCH] Creating stock moves for {self.name}")
        
        # Get locations
        courier_location = self.env.ref('pos_courier_dispatch.stock_location_courier_transit', raise_if_not_found=False)
        if not courier_location:
            raise UserError(_('Courier Transit location not found. Please check module installation.'))
        
        # Get source location from POS config
        source_location = self.pos_order_id.config_id.picking_type_id.default_location_src_id
        if not source_location:
            raise UserError(_('Cannot determine source location from POS configuration.'))
        
        stock_move_obj = self.env['stock.move']
        
        for line in self.line_ids:
            if line.quantity <= 0:
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
            
            _logger.info(f"[COURIER_DISPATCH] Created stock move for {line.product_id.name}: {line.quantity} units")
    
    def _create_payment_entry(self):
        """Create journal entry for company-paid courier fee"""
        self.ensure_one()
        
        if not self.payment_journal_id:
            raise UserError(_('Payment journal is required when company pays courier fee.'))
        
        if self.company_fee_portion <= 0:
            return
        
        _logger.info(f"[COURIER_DISPATCH] Creating payment entry for {self.name}: {self.company_fee_portion}")
        
        # Get COGS account from settings
        cogs_account_param = self.env['ir.config_parameter'].sudo().get_param('pos_courier_dispatch.courier_cogs_account_id')
        if not cogs_account_param:
            raise UserError(_(
                'Courier COGS account not configured. '
                'Please configure it in System Parameters: pos_courier_dispatch.courier_cogs_account_id'
            ))
        
        cogs_account_id = self.env['account.account'].browse(int(cogs_account_param))
        if not cogs_account_id.exists():
            raise UserError(_(
                'Configured COGS account (ID: %s) does not exist. '
                'Please check System Parameters: pos_courier_dispatch.courier_cogs_account_id'
            ) % cogs_account_param)
        
        # Get payment account from journal
        payment_account = self.payment_journal_id.default_account_id
        if not payment_account:
            raise UserError(_('Payment journal %s has no default account configured.') % self.payment_journal_id.name)
        
        # Create journal entry
        move_vals = {
            'journal_id': self.payment_journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': self.name,
            'line_ids': [
                # Debit: COGS
                (0, 0, {
                    'account_id': cogs_account_id.id,
                    'name': f'Courier fee: {self.name}',
                    'debit': self.company_fee_portion,
                    'credit': 0.0,
                }),
                # Credit: Bank/Cash
                (0, 0, {
                    'account_id': payment_account.id,
                    'name': f'Courier payment: {self.name}',
                    'debit': 0.0,
                    'credit': self.company_fee_portion,
                }),
            ],
        }
        
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        
        self.payment_move_id = move.id
        
        _logger.info(f"[COURIER_DISPATCH] Payment entry created: {move.name}")


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    courier_dispatch_id = fields.Many2one(
        'courier.dispatch',
        string='Courier Dispatch',
        ondelete='cascade',
        index=True,
    )
