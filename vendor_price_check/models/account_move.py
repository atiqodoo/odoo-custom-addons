# vendor_price_check/models/account_move.py
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

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

    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _check_vendor_bill_prices(self):
        """
        Check for pricing discrepancies in vendor bill lines.
        
        This method compares current bill prices against historical prices
        from previous bills for the same products and vendor.
        
        Comparison can be done against:
        - Lowest historical price
        - Average historical price
        - Both (configurable via system parameters)
        
        Returns:
            list: IDs of created vendor.price.discrepancy records
        """
        self.ensure_one()
        _logger.info("🔍 Checking prices for bill %s", self.name or 'Unnamed')
        
        # Clear existing discrepancies before rechecking
        self.discrepancy_ids.unlink()
        
        # Get wizard prices if coming from wizard context
        wizard_prices = self.env.context.get('wizard_vendor_prices', {})
        
        # Fetch system configuration parameters
        bill_count = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'vendor_price_check.bill_count', 
                '5'
            )
        )
        comparison_mode = self.env['ir.config_parameter'].sudo().get_param(
            'vendor_price_check.comparison_mode', 
            'both'
        )
        allow_no_history = self.env['ir.config_parameter'].sudo().get_param(
            'vendor_price_check.allow_no_history', 
            'false'
        ) == 'true'

        _logger.debug(
            "Using bill_count: %s, comparison_mode: %s, allow_no_history: %s", 
            bill_count, 
            comparison_mode, 
            allow_no_history
        )

        discrepancies = []
        
        # Loop through all invoice lines with products
        for line in self.invoice_line_ids.filtered(
            lambda l: l.product_id and l.move_id.move_type == 'in_invoice'
        ):
            product = line.product_id
            
            # Determine current price with priority:
            # 1. Wizard vendor prices (if set)
            # 2. Net price (if custom pricing is used)
            # 3. Standard price_unit
            current_price = wizard_prices.get(
                product.id, 
                line.net_price if getattr(line, 'use_custom_pricing', False) else line.price_unit
            )

            # Check against vendor pricing rules if no wizard price provided
            if product.id not in wizard_prices:
                pricing_rule = self.env['product.supplierinfo'].search([
                    ('product_id', '=', product.id),
                    ('partner_id', '=', self.partner_id.id),
                    ('min_qty', '<=', line.quantity),
                    '|', 
                    ('max_qty', '=', 0), 
                    ('max_qty', '>=', line.quantity),
                ], limit=1)
                
                if pricing_rule:
                    # Calculate price with discount and freight
                    current_price = (
                        pricing_rule.price * 
                        (1 - (pricing_rule.discount_percentage or 0.0) / 100) * 
                        (1 + (pricing_rule.freight_percentage or 0.0) / 100)
                    )
                    _logger.debug(
                        f"Using vendor pricing rule for {product.display_name}: {current_price}"
                    )

            # Search for historical bill lines for the same product
            domain = [
                ('product_id', '=', product.id),
                ('move_id.move_type', '=', 'in_invoice'),
                ('move_id.state', '=', 'posted'),
                ('move_id.id', '!=', self.id),
            ]
            historical_lines = self.env['account.move.line'].search(
                domain, 
                limit=bill_count, 
                order='date desc'
            )
            
            # Skip if no history and configuration doesn't allow it
            if not historical_lines and not allow_no_history:
                continue

            # Calculate historical price statistics
            prices = historical_lines.mapped('net_price') or [0]
            lowest_price = min(prices)
            average_price = sum(prices) / len(prices) if prices else 0
            price_diff_lowest = current_price - lowest_price
            price_diff_average = current_price - average_price
            percentage_diff_lowest = (
                (price_diff_lowest / lowest_price * 100) if lowest_price else 100
            )
            percentage_diff_average = (
                (price_diff_average / average_price * 100) if average_price else 100
            )

            # Create discrepancy record if price is higher than historical
            if (comparison_mode in ('lowest', 'both') and price_diff_lowest > 0.01) or \
               (comparison_mode in ('average', 'both') and price_diff_average > 0.01):
                _logger.warning(f"Discrepancy detected for {product.display_name}")
                
                discrepancy = self.env['vendor.price.discrepancy'].create({
                    'bill_id': self.id,
                    'product_id': product.id,
                    'vendor_id': self.partner_id.id,
                    'vendor_price': current_price,
                    'lowest_price': lowest_price,
                    'average_price': average_price,
                    'price_difference_lowest': price_diff_lowest,
                    'percentage_diff_lowest': percentage_diff_lowest,
                    'price_difference_average': price_diff_average,
                    'percentage_diff_average': percentage_diff_average,
                    'bill_count': len(historical_lines),
                })
                discrepancies.append(discrepancy.id)

        return discrepancies

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
        _logger.info(f"✓ Discrepancies approved by {self.env.user.name}")
        
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