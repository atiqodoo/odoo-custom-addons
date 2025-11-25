# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, date
import base64
import io
import logging

# Setup logger for debugging
_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
    _logger.warning("xlsxwriter not installed - Excel export will not work")


class StockCardWizard(models.TransientModel):
    _name = 'stock.card.wizard'
    _description = 'Stock Card Report Wizard'

    product_ids = fields.Many2many(
        'product.product',
        string='Products',
        domain=[],
        help='Leave empty for all products. Type product name or code to search. Accepts all product types.'
    )
    location_ids = fields.Many2many(
        'stock.location',
        string='Locations',
        domain=[('usage', '=', 'internal')],
        help='Stock locations to include in report'
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        help='Auto-fills internal locations of warehouse'
    )
    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: date(date.today().year, 1, 1)
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.context_today
    )
    show_internal_transfers = fields.Boolean(
        string='Show Internal Transfers',
        default=False,
        help='Include internal location movements (creates 2 lines per transfer)'
    )
    group_by_product = fields.Boolean(
        string='Separate Page Per Product',
        default=True,
        help='Each product on separate page (for multi-product reports)'
    )
    
    excel_file = fields.Binary('Excel File', readonly=True)
    excel_filename = fields.Char('Excel Filename', readonly=True)
    
    debug_info = fields.Text('Debug Information', readonly=True, help='Diagnostic information')
    product_count_available = fields.Integer('Available Products', compute='_compute_product_stats', store=False)
    
    @api.model
    def default_get(self, fields_list):
        """Override to add debug logging"""
        _logger.info("=" * 80)
        _logger.info("STOCK CARD WIZARD: default_get called")
        _logger.info(f"Fields requested: {fields_list}")
        
        res = super(StockCardWizard, self).default_get(fields_list)
        
        try:
            products = self.env['product.product'].search([])
            _logger.info(f"Total products found (all types): {len(products)}")
            if len(products) > 0:
                _logger.info(f"Sample products: {products[:5].mapped('display_name')}")
                types = {}
                for p in products:
                    types[p.type] = types.get(p.type, 0) + 1
                _logger.info(f"Product types: {types}")
            else:
                _logger.warning("NO PRODUCTS FOUND")
            
            user = self.env.user
            _logger.info(f"Current user: {user.name} (ID: {user.id})")
            
            debug_lines = [
                f"Products available: {len(products)} (all types)",
                f"User: {user.name}",
                f"Database: {self.env.cr.dbname}",
                f"Context: {self.env.context}",
            ]
            res['debug_info'] = '\n'.join(debug_lines)
            
        except Exception as e:
            _logger.error(f"Error in default_get debug: {e}", exc_info=True)
        
        _logger.info(f"Returning defaults: {res}")
        _logger.info("=" * 80)
        return res
    
    @api.depends('product_ids')
    def _compute_product_stats(self):
        """Compute product statistics for debugging"""
        for wizard in self:
            try:
                available = self.env['product.product'].search_count([])
                wizard.product_count_available = available
                _logger.info(f"Product stats computed: {available} products available (all types)")
            except Exception as e:
                _logger.error(f"Error computing product stats: {e}")
                wizard.product_count_available = 0
    
    @api.onchange('product_ids')
    def _onchange_product_ids(self):
        """Debug logging for product selection changes"""
        _logger.info("=" * 80)
        _logger.info("PRODUCT SELECTION CHANGED")
        _logger.info(f"Selected products: {self.product_ids.mapped('display_name')}")
        _logger.info(f"Product IDs: {self.product_ids.ids}")
        _logger.info("=" * 80)

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        """Auto-populate locations when warehouse is selected"""
        _logger.info("=" * 80)
        _logger.info("WAREHOUSE CHANGED")
        _logger.info(f"Warehouse: {self.warehouse_id.name if self.warehouse_id else 'None'}")
        
        if self.warehouse_id:
            locations = self.env['stock.location'].search([
                ('id', 'child_of', self.warehouse_id.view_location_id.id),
                ('usage', '=', 'internal')
            ])
            _logger.info(f"Found {len(locations)} locations in warehouse")
            _logger.info(f"Locations: {locations.mapped('complete_name')}")
            self.location_ids = locations
        else:
            _logger.info("No warehouse selected")
        
        _logger.info("=" * 80)

    def action_print_pdf(self):
        """Generate PDF report"""
        _logger.info("=" * 80)
        _logger.info("ACTION: PRINT PDF CLICKED")
        _logger.info(f"Wizard ID: {self.id}")
        _logger.info(f"Products selected: {self.product_ids.mapped('display_name')}")
        _logger.info(f"Product IDs: {self.product_ids.ids}")
        _logger.info(f"Locations: {self.location_ids.mapped('complete_name')}")
        _logger.info(f"Date range: {self.date_from} to {self.date_to}")
        _logger.info(f"Show internal transfers: {self.show_internal_transfers}")
        
        self.ensure_one()
        if not self.location_ids:
            _logger.error("No locations selected - raising UserError")
            raise UserError(_('Please select at least one location.'))
        
        _logger.info("Preparing stock card data...")
        try:
            data = self._prepare_stock_card_data()
            _logger.info(f"Data prepared successfully. Products in report: {len(data.get('products_data', []))}")
        except Exception as e:
            _logger.error(f"Error preparing data: {e}", exc_info=True)
            raise
        
        _logger.info("Generating PDF report...")
        result = self.env.ref('enhanced_stock_card.action_report_stock_card').report_action(self, data=data)
        _logger.info(f"PDF report action returned: {result}")
        _logger.info("=" * 80)
        return result

    def action_export_excel(self):
        """Export stock card to Excel"""
        _logger.info("=" * 80)
        _logger.info("ACTION: EXPORT EXCEL CLICKED")
        
        self.ensure_one()
        if not xlsxwriter:
            _logger.error("xlsxwriter not installed")
            raise UserError(_('Please install xlsxwriter Python library: pip install xlsxwriter'))
        
        if not self.location_ids:
            _logger.error("No locations selected")
            raise UserError(_('Please select at least one location.'))
        
        _logger.info("Preparing data for Excel export...")
        data = self._prepare_stock_card_data()
        
        _logger.info("Generating Excel file...")
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        self._create_excel_report(workbook, data)
        
        workbook.close()
        output.seek(0)
        
        filename = f"stock_card_{self.date_from}_{self.date_to}.xlsx"
        self.write({
            'excel_file': base64.b64encode(output.read()),
            'excel_filename': filename,
        })
        
        _logger.info(f"Excel file created: {filename}")
        _logger.info("=" * 80)
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=stock.card.wizard&id={self.id}&field=excel_file&download=true&filename={filename}',
            'target': 'new',
        }
    
    def action_debug_test(self):
        """Debug action to test product access"""
        _logger.info("=" * 80)
        _logger.info("DEBUG TEST ACTION CALLED")
        
        try:
            all_products = self.env['product.product'].search([])
            _logger.info(f"Test 1 - All products: {len(all_products)}")
            
            storable = self.env['product.product'].search([('type', '=', 'product')])
            consumable = self.env['product.product'].search([('type', '=', 'consu')])
            service = self.env['product.product'].search([('type', '=', 'service')])
            _logger.info(f"Test 2 - Storable products: {len(storable)}")
            _logger.info(f"Test 2 - Consumable products: {len(consumable)}")
            _logger.info(f"Test 2 - Service products: {len(service)}")
            
            message = f"""
DEBUG TEST RESULTS (ALL PRODUCT TYPES):
=======================================
✓ Total products: {len(all_products)}
✓ Storable: {len(storable)}
✓ Consumable: {len(consumable)}
✓ Service: {len(service)}

Check Odoo server logs for detailed information.
            """
            
            _logger.info("DEBUG TEST COMPLETED SUCCESSFULLY")
            _logger.info("=" * 80)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Debug Test Completed',
                    'message': message,
                    'type': 'success',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            _logger.error(f"DEBUG TEST FAILED: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Debug Test Failed',
                    'message': f'Error: {str(e)}\n\nCheck server logs for details.',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_debug_moves(self):
        """Debug action to test moves querying"""
        _logger.info("=" * 80)
        _logger.info("DEBUG MOVES ACTION CALLED")
        
        try:
            self.ensure_one()
            if not self.product_ids or not self.location_ids:
                _logger.error("No products or locations selected")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Debug Failed',
                        'message': 'Please select at least one product and location.',
                        'type': 'warning',
                        'sticky': True,
                    }
                }
            
            product = self.product_ids[0]
            location_ids = self.location_ids.ids
            
            _logger.info(f"Testing moves for product: {product.display_name}")
            _logger.info(f"Locations: {[loc.complete_name for loc in self.location_ids]}")
            
            moves_domain = [
                ('product_id', '=', product.id),
                ('state', '=', 'done'),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ]
            all_moves = self.env['stock.move'].search(moves_domain)
            _logger.info(f"Test 1 - All moves in period: {len(all_moves)}")
            
            location_domain = moves_domain + [
                '|',
                ('location_id', 'in', location_ids),
                ('location_dest_id', 'in', location_ids),
            ]
            location_moves = self.env['stock.move'].search(location_domain)
            _logger.info(f"Test 2 - Moves affecting locations: {len(location_moves)}")
            
            message = f"""
MOVES DEBUG RESULTS:
====================
Product: {product.display_name}
Locations: {len(self.location_ids)}
Date Range: {self.date_from} to {self.date_to}

✓ Total moves in period: {len(all_moves)}
✓ Moves affecting locations: {len(location_moves)}

Check Odoo server logs for complete details.
            """
            
            _logger.info("MOVES DEBUG COMPLETED")
            _logger.info("=" * 80)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Moves Debug Results',
                    'message': message,
                    'type': 'info',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            _logger.error(f"MOVES DEBUG FAILED: {e}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Moves Debug Failed',
                    'message': f'Error: {str(e)}\n\nCheck server logs for details.',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def _prepare_stock_card_data(self):
        """Main method to prepare all stock card data"""
        self.ensure_one()
        
        _logger.info("=" * 80)
        _logger.info("PREPARING STOCK CARD DATA")
        _logger.info(f"Selected products: {len(self.product_ids)}")
        _logger.info(f"Selected locations: {len(self.location_ids)}")
        _logger.info(f"Date range: {self.date_from} to {self.date_to}")
        
        products = self.product_ids if self.product_ids else self.env['product.product'].search([('type', 'in', ['product', 'consu'])])
        
        _logger.info(f"Products to process: {len(products)}")
        _logger.info(f"Product names: {products.mapped('display_name')}")
        
        result = {
            'wizard': self,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'locations': self.location_ids,
            'products_data': [],
            'company': self.env.company,
        }
        
        for product in products:
            _logger.info(f"Processing product: {product.display_name} (ID: {product.id})")
            product_data = self._get_product_stock_card(product)
            if product_data['moves'] or product_data['opening']['qty']:
                result['products_data'].append(product_data)
                _logger.info(f"✓ Added product data with {len(product_data['moves'])} moves")
            else:
                _logger.info(f"✗ Skipped product - no moves or opening balance")
        
        _logger.info(f"Final result: {len(result['products_data'])} products with data")
        _logger.info("=" * 80)
        return result

    def _get_product_stock_card(self, product):
        """Get stock card data for a single product"""
        _logger.info(f"Getting stock card for product: {product.display_name}")
        
        _logger.info("Calculating opening balance...")
        opening = self._calculate_opening_balance(product)
        _logger.info(f"Opening balance - Qty: {opening['qty']}, Value: {opening['value']}")
        
        _logger.info("Fetching stock moves data...")
        moves_data = self._get_stock_moves_data(product)
        _logger.info(f"Found {len(moves_data)} stock moves")
        
        _logger.info("Calculating running totals...")
        moves_with_totals = self._calculate_running_totals(moves_data, opening)
        
        _logger.info("Calculating closing balance...")
        closing = self._calculate_closing(moves_with_totals, opening)
        _logger.info(f"Closing balance - Qty: {closing['qty']}, Value: {closing['value']}")
        
        return {
            'product': product,
            'opening': opening,
            'moves': moves_with_totals,
            'closing': closing,
        }

    def _calculate_opening_balance(self, product):
        """Calculate opening balance from valuation layers before date_from"""
        location_ids = self.location_ids.ids
        
        _logger.info(f"Calculating opening balance for product {product.display_name}")
        _logger.info(f"Using locations: {location_ids}")
        
        domain = [
            ('product_id', '=', product.id),
            ('create_date', '<', fields.Datetime.to_datetime(self.date_from)),
        ]
        
        layers = self.env['stock.valuation.layer'].search(domain)
        _logger.info(f"Found {len(layers)} valuation layers before {self.date_from}")
        
        opening_qty = 0.0
        opening_value = 0.0
        opening_purchase = 0.0
        opening_pos = 0.0
        
        for layer in layers:
            if layer.stock_move_id:
                move = layer.stock_move_id
                if move.location_dest_id.id in location_ids and move.location_id.usage != 'internal':
                    opening_qty += layer.quantity
                    opening_value += layer.value
                    if move.purchase_line_id:
                        purchase_amount, _ = self._get_purchase_amount_and_unit_price(move)
                        opening_purchase += purchase_amount
                    pos_amount, _ = self._get_pos_amount_and_unit_price(move)
                    opening_pos += pos_amount
                elif move.location_id.id in location_ids and move.location_dest_id.usage != 'internal':
                    opening_qty -= layer.quantity
                    opening_value -= layer.value
        
        opening_unit_cost = opening_value / opening_qty if opening_qty else 0.0
        
        _logger.info(f"Opening balance calculated: Qty={opening_qty}, Value={opening_value}, Unit Cost={opening_unit_cost}")
        
        return {
            'qty': opening_qty,
            'value': opening_value,
            'unit_cost': opening_unit_cost,
            'purchase_total': opening_purchase,
            'pos_total': opening_pos,
        }

    def _get_stock_moves_data(self, product):
        """Get all stock moves for the product in date range"""
        location_ids = self.location_ids.ids
        
        _logger.info("=" * 60)
        _logger.info(f"GETTING STOCK MOVES FOR PRODUCT: {product.display_name}")
        _logger.info(f"Product ID: {product.id}")
        _logger.info(f"Location IDs: {location_ids}")
        _logger.info(f"Date range: {self.date_from} to {self.date_to}")
        _logger.info(f"Show internal transfers: {self.show_internal_transfers}")
        
        date_from_dt = fields.Datetime.to_datetime(self.date_from)
        date_to_dt = fields.Datetime.to_datetime(self.date_to)
        
        _logger.info(f"Date from (datetime): {date_from_dt}")
        _logger.info(f"Date to (datetime): {date_to_dt}")
        
        domain = [
            ('product_id', '=', product.id),
            ('state', '=', 'done'),
            ('date', '>=', date_from_dt),
            ('date', '<=', date_to_dt),
            '|',
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'in', location_ids),
        ]
        
        if not self.show_internal_transfers:
            domain.extend(['|', ('location_id.usage', '!=', 'internal'), ('location_dest_id.usage', '!=', 'internal')])
        
        _logger.info(f"Final domain: {domain}")
        
        moves = self.env['stock.move'].search(domain, order='date, id')
        _logger.info(f"FOUND {len(moves)} STOCK MOVES")
        
        moves_data = []
        for i, move in enumerate(moves):
            _logger.info(f"Move {i+1}/{len(moves)}:")
            _logger.info(f"  ID: {move.id}")
            _logger.info(f"  Date: {move.date}")
            _logger.info(f"  Reference: {move.reference}")
            _logger.info(f"  Product: {move.product_id.display_name}")
            _logger.info(f"  Quantity: {move.quantity}")
            _logger.info(f"  From: {move.location_id.complete_name} (ID: {move.location_id.id})")
            _logger.info(f"  To: {move.location_dest_id.complete_name} (ID: {move.location_dest_id.id})")
            _logger.info(f"  State: {move.state}")
            _logger.info(f"  Move Type: {self._determine_move_type(move)}")
            
            move_dict = self._prepare_move_data(move, location_ids)
            if move_dict:
                moves_data.append(move_dict)
                _logger.info(f"  ✓ ADDED TO MOVES DATA")
            else:
                _logger.info(f"  ✗ SKIPPED - doesn't affect selected locations")
            
            _logger.info(f"  {'-' * 40}")
        
        _logger.info(f"TOTAL MOVES PROCESSED: {len(moves_data)}")
        _logger.info("=" * 60)
        return moves_data

    def _get_pos_amount_and_unit_price(self, move):
        """
        Get POS amount and unit price from related POS order line
        
        This method retrieves the actual amount collected from the customer
        INCLUDING ALL TAXES (price_subtotal_incl) for a stock move that
        originated from a POS sale.
        
        Args:
            move: stock.move record - the inventory movement
            
        Returns:
            tuple: (total_amount, unit_price)
                - total_amount: Total amount collected INCLUDING tax (e.g., 87.00)
                - unit_price: Price per unit INCLUDING tax (e.g., 29.00)
                - Returns (0.0, 0.0) if not a POS sale
                
        Example:
            Sale: 3 units @ 25.00 + 16% VAT
            Returns: (87.00, 29.00)
        """
        
        # ============================================================================
        # STEP 1: VERIFY THIS IS A POS SALE
        # ============================================================================
        _logger.info("=" * 80)
        _logger.info("POS AMOUNT RETRIEVAL - START")
        _logger.info(f"Processing Stock Move ID: {move.id}")
        _logger.info(f"Move Reference: {move.reference or move.name}")
        _logger.info(f"Product: {move.product_id.display_name} (ID: {move.product_id.id})")
        
        # Check if move has a picking (delivery order)
        if not move.picking_id:
            _logger.info("❌ NO PICKING - This move has no delivery order")
            _logger.info("   Reason: Stock move not linked to any picking")
            _logger.info("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        _logger.info(f"✓ Picking Found: {move.picking_id.name} (ID: {move.picking_id.id})")
        
        # Check if picking has a POS order
        if not move.picking_id.pos_order_id:
            _logger.info("❌ NO POS ORDER - This picking is not from a POS sale")
            _logger.info(f"   Picking Type: {move.picking_id.picking_type_id.name}")
            _logger.info("   Reason: Could be regular sale, purchase, or internal transfer")
            _logger.info("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        # ============================================================================
        # STEP 2: GET THE POS ORDER
        # ============================================================================
        pos_order = move.picking_id.pos_order_id
        _logger.info(f"✓ POS Order Found: {pos_order.name} (ID: {pos_order.id})")
        _logger.info(f"   POS Session: {pos_order.session_id.name if pos_order.session_id else 'N/A'}")
        _logger.info(f"   Order Date: {pos_order.date_order}")
        _logger.info(f"   Order State: {pos_order.state}")
        _logger.info(f"   Total Lines in Order: {len(pos_order.lines)}")
        
        # Log all products in the POS order for debugging
        _logger.info("   Products in POS Order:")
        for idx, line in enumerate(pos_order.lines, 1):
            _logger.info(f"     {idx}. {line.product_id.display_name} - Qty: {line.qty}")
        
        # ============================================================================
        # STEP 3: FIND MATCHING PRODUCT LINES
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("SEARCHING FOR MATCHING PRODUCT LINES")
        _logger.info(f"Looking for: {move.product_id.display_name} (ID: {move.product_id.id})")
        
        # Filter to find lines that match our product and have positive quantity
        pos_lines = pos_order.lines.filtered(
            lambda l: l.product_id == move.product_id and l.qty > 0
        )
        
        _logger.info(f"Found {len(pos_lines)} matching line(s)")
        
        if not pos_lines:
            _logger.warning("⚠️ NO MATCHING LINES FOUND")
            _logger.warning(f"   Product {move.product_id.display_name} not found in POS order")
            _logger.warning("   This could indicate a data inconsistency")
            _logger.warning("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        # ============================================================================
        # STEP 4: LOG DETAILS OF EACH MATCHING LINE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("MATCHED LINE DETAILS:")
        
        for idx, line in enumerate(pos_lines, 1):
            _logger.info(f"\n  Line #{idx}:")
            _logger.info(f"    Product: {line.product_id.display_name}")
            _logger.info(f"    Quantity: {line.qty}")
            _logger.info(f"    Price Unit (base): {line.price_unit}")
            _logger.info(f"    Discount: {line.discount}%")
            
            # Calculate discount factor
            discount_factor = (100 - (line.discount or 0.0)) / 100.0
            price_after_discount = line.price_unit * discount_factor
            _logger.info(f"    Price after discount: {price_after_discount}")
            
            # Log tax information
            tax_names = ', '.join(line.tax_ids.mapped('name')) if line.tax_ids else 'No taxes'
            tax_amount = line.price_subtotal_incl - line.price_subtotal
            _logger.info(f"    Taxes: {tax_names}")
            _logger.info(f"    Tax Amount: {tax_amount}")
            
            # Log the key amounts
            _logger.info(f"    💰 price_subtotal (WITHOUT tax): {line.price_subtotal}")
            _logger.info(f"    💰 price_subtotal_incl (WITH tax): {line.price_subtotal_incl} ⬅️ USING THIS")
            
        # ============================================================================
        # STEP 5: GET QUANTITY FROM STOCK MOVE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("QUANTITY VERIFICATION:")
        
        # Get quantity - try 'quantity' first, fallback to 'product_uom_qty'
        qty = move.quantity or move.product_uom_qty
        
        _logger.info(f"  move.quantity: {move.quantity}")
        _logger.info(f"  move.product_uom_qty: {move.product_uom_qty}")
        _logger.info(f"  ✓ Using Quantity: {qty}")
        
        if not qty:
            _logger.error("❌ ZERO QUANTITY")
            _logger.error("   Both move.quantity and move.product_uom_qty are 0 or None")
            _logger.error("   Cannot calculate unit price with zero quantity")
            _logger.error("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        # ============================================================================
        # STEP 6: CALCULATE TOTAL AMOUNT (WITH TAX)
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("CALCULATING TOTAL AMOUNT (INCLUDING TAX):")
        
        # Sum all matching lines using price_subtotal_incl (includes tax)
        total_amount = sum(pos_lines.mapped('price_subtotal_incl'))
        
        _logger.info(f"  Number of lines to sum: {len(pos_lines)}")
        
        # Log individual line contributions
        for idx, line in enumerate(pos_lines, 1):
            _logger.info(f"  Line {idx} contribution: {line.price_subtotal_incl}")
        
        _logger.info(f"  ✓ Total Amount (WITH tax): {total_amount}")
        
        # Also log what it would be WITHOUT tax for comparison
        total_without_tax = sum(pos_lines.mapped('price_subtotal'))
        tax_amount = total_amount - total_without_tax
        _logger.info(f"  ℹ️ For comparison:")
        _logger.info(f"     Total WITHOUT tax: {total_without_tax}")
        _logger.info(f"     Tax Amount: {tax_amount}")
        
        # ============================================================================
        # STEP 7: CALCULATE UNIT PRICE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("CALCULATING UNIT PRICE:")
        
        unit_price = total_amount / qty if qty else 0.0
        
        _logger.info(f"  Formula: total_amount / quantity")
        _logger.info(f"  Calculation: {total_amount} / {qty}")
        _logger.info(f"  ✓ Unit Price (WITH tax): {unit_price}")
        
        # Also log unit price WITHOUT tax for comparison
        unit_price_without_tax = total_without_tax / qty if qty else 0.0
        _logger.info(f"  ℹ️ For comparison:")
        _logger.info(f"     Unit Price WITHOUT tax: {unit_price_without_tax}")
        
        # ============================================================================
        # STEP 8: VALIDATION CHECKS
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("VALIDATION CHECKS:")
        
        # Check if amounts are reasonable
        if total_amount < 0:
            _logger.warning("⚠️ NEGATIVE AMOUNT DETECTED")
            _logger.warning(f"   Total Amount: {total_amount}")
            _logger.warning("   This might indicate a return or refund")
        
        if unit_price < 0:
            _logger.warning("⚠️ NEGATIVE UNIT PRICE DETECTED")
            _logger.warning(f"   Unit Price: {unit_price}")
        
        # Check if quantity in POS matches stock move
        total_pos_qty = sum(pos_lines.mapped('qty'))
        if abs(total_pos_qty - qty) > 0.01:  # Allow small rounding difference
            _logger.warning("⚠️ QUANTITY MISMATCH")
            _logger.warning(f"   POS Order Total Qty: {total_pos_qty}")
            _logger.warning(f"   Stock Move Qty: {qty}")
            _logger.warning("   This might indicate partial delivery or split orders")
        else:
            _logger.info(f"  ✓ Quantity Match: POS qty ({total_pos_qty}) = Move qty ({qty})")
        
        # ============================================================================
        # STEP 9: FINAL RESULT
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("FINAL RESULT:")
        _logger.info(f"  ✅ Total Amount (INCLUDING tax): {total_amount}")
        _logger.info(f"  ✅ Unit Price (INCLUDING tax): {unit_price}")
        _logger.info(f"  📊 This will appear in Stock Card Report as:")
        _logger.info(f"     POS Unit Price: {unit_price:.2f}")
        _logger.info(f"     POS Amount: {total_amount:.2f}")
        _logger.info("POS AMOUNT RETRIEVAL - COMPLETE")
        _logger.info("=" * 80)
        
        # Return the tuple
        return (total_amount, unit_price)

    def _get_purchase_amount_and_unit_price(self, move):
        """
        Get purchase amount and unit price - ENHANCED with tax inclusion and custom pricing support
        
        This method retrieves the actual amount paid to the vendor INCLUDING ALL TAXES
        for a stock move that originated from a purchase order. It intelligently handles:
        - Posted vendor bills (preferred source)
        - Custom pricing with discounts and freight
        - Standard Odoo pricing
        - RFQ/PO amounts (fallback when no bill exists)
        
        Args:
            move: stock.move record - the inventory movement
            
        Returns:
            tuple: (total_amount, unit_price)
                - total_amount: Total amount paid INCLUDING tax (e.g., 10,523.52)
                - unit_price: Price per unit INCLUDING tax (e.g., 877.00)
                - Returns (0.0, 0.0) if not a purchase
                
        Example:
            Purchase: 12 units @ 756.00 net + 16% VAT
            Returns: (10,523.52, 877.00)
        """
        
        # ============================================================================
        # STEP 1: VERIFY THIS IS A PURCHASE
        # ============================================================================
        _logger.info("=" * 80)
        _logger.info("PURCHASE AMOUNT RETRIEVAL - START")
        _logger.info(f"Processing Stock Move ID: {move.id}")
        _logger.info(f"Move Reference: {move.reference or move.name}")
        _logger.info(f"Product: {move.product_id.display_name} (ID: {move.product_id.id})")
        
        if not move.purchase_line_id:
            _logger.info("❌ NO PURCHASE LINE - This move is not from a purchase order")
            _logger.info("   Reason: Stock move not linked to any purchase.order.line")
            _logger.info("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        # ============================================================================
        # STEP 2: GET PURCHASE ORDER INFORMATION
        # ============================================================================
        purchase_line = move.purchase_line_id
        purchase_order = purchase_line.order_id
        
        _logger.info(f"✓ Purchase Order Found: {purchase_order.name} (ID: {purchase_order.id})")
        _logger.info(f"   Vendor: {purchase_order.partner_id.name}")
        _logger.info(f"   Order State: {purchase_order.state}")
        _logger.info(f"   Order Date: {purchase_order.date_order}")
        _logger.info(f"   Invoice Status: {purchase_order.invoice_status}")
        _logger.info(f"   Total Order Lines: {len(purchase_order.order_line)}")
        
        # ============================================================================
        # STEP 3: CHECK FOR CUSTOM PRICING MODULE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("CHECKING FOR CUSTOM PRICING MODULE:")
        
        # Check if custom pricing fields exist
        has_custom_pricing_field = hasattr(purchase_line, 'use_custom_pricing')
        has_net_price_field = hasattr(purchase_line, 'net_price')
        
        _logger.info(f"  Custom Pricing Module Installed: {'✓ Yes' if has_custom_pricing_field else '✗ No'}")
        _logger.info(f"  Net Price Field Available: {'✓ Yes' if has_net_price_field else '✗ No'}")
        
        if has_custom_pricing_field:
            use_custom_pricing = purchase_line.use_custom_pricing
            _logger.info(f"  Custom Pricing Enabled for this line: {'✓ Yes' if use_custom_pricing else '✗ No'}")
            
            if use_custom_pricing and has_net_price_field:
                _logger.info(f"  Applied Discount: {getattr(purchase_line, 'applied_discount', 0.0)}%")
                _logger.info(f"  Applied Freight: {getattr(purchase_line, 'applied_freight', 0.0)}%")
                _logger.info(f"  Net Price (per unit): {purchase_line.net_price}")
        else:
            use_custom_pricing = False
            _logger.info("  Using standard Odoo pricing")
        
        # ============================================================================
        # STEP 4: SEARCH FOR POSTED BILLS (PREFERRED SOURCE)
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("SEARCHING FOR POSTED BILLS (VENDOR INVOICES):")
        
          # Log ALL invoices first
        _logger.info(f"  Total invoices linked to PO: {len(purchase_order.invoice_ids)}")
        for idx, inv in enumerate(purchase_order.invoice_ids, 1):
            _logger.info(f"    Invoice #{idx}: {inv.name}")
            _logger.info(f"      State: {inv.state}")
            _logger.info(f"      Move Type: {inv.move_type}")
            _logger.info(f"      Will be included: {inv.state == 'posted' and inv.move_type in ('in_invoice', 'in_refund')}")
        
        # Check if there are posted bills (invoices) for this purchase order
        posted_bills = purchase_order.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.move_type in ('in_invoice', 'in_refund')
        )
        
        _logger.info(f"  Purchase Order has {len(purchase_order.invoice_ids)} invoice(s)")
        _logger.info(f"  Posted Bills Found: {len(posted_bills)}")
        
        if posted_bills:
            for idx, bill in enumerate(posted_bills, 1):
                _logger.info(f"    Bill #{idx}: {bill.name} - State: {bill.state} - Amount: {bill.amount_total}")
        
        # ============================================================================
        # STEP 5: GET QUANTITY FROM STOCK MOVE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("QUANTITY VERIFICATION:")
        
        qty = move.quantity or move.product_uom_qty
        
        _logger.info(f"  move.quantity: {move.quantity}")
        _logger.info(f"  move.product_uom_qty: {move.product_uom_qty}")
        _logger.info(f"  ✓ Using Quantity: {qty}")
        
        if not qty or qty <= 0:
            _logger.error("❌ INVALID QUANTITY")
            _logger.error(f"   Quantity is {qty} (must be > 0)")
            _logger.error("   Cannot calculate unit price with zero or negative quantity")
            _logger.error("   Returning: (0.0, 0.0)")
            _logger.info("=" * 80)
            return (0.0, 0.0)
        
        # ============================================================================
        # STEP 6: CALCULATE AMOUNT FROM POSTED BILLS (PREFERRED)
        # ============================================================================
        # ============================================================================
        # STEP 6: CALCULATE AMOUNT FROM POSTED BILLS (PREFERRED)
        # ============================================================================
        total_amount = 0.0
        amount_source = "Unknown"
        
        if posted_bills:
            _logger.info("-" * 80)
            _logger.info("CALCULATING FROM POSTED BILLS (ACTUAL PAYMENT):")
            
            # Find invoice lines for this product
            for bill in posted_bills:
                _logger.info(f"\n  Processing Bill: {bill.name}")
                _logger.info(f"    Bill ID: {bill.id}")
                _logger.info(f"    Total Invoice Lines: {len(bill.invoice_line_ids)}")
                
                # Log ALL invoice lines for debugging
                _logger.info(f"    All lines in bill:")
                for idx, line in enumerate(bill.invoice_line_ids, 1):
                    _logger.info(f"      Line #{idx}:")
                    _logger.info(f"        Product ID: {line.product_id.id if line.product_id else 'None'}")
                    _logger.info(f"        Product Name: {line.product_id.display_name if line.product_id else 'N/A'}")
                    _logger.info(f"        Display Type: {line.display_type if line.display_type else 'False'}")
                    _logger.info(f"        Quantity: {line.quantity}")
                    _logger.info(f"        Price Unit: {line.price_unit}")
                
                # Now try to filter
                _logger.info(f"\n    Looking for product ID: {move.product_id.id}")
                _logger.info(f"    Looking for product name: {move.product_id.display_name}")
                
                invoice_lines = bill.invoice_line_ids.filtered(
                    lambda line: line.product_id == move.product_id and line.display_type not in ('line_section', 'line_note')
                )
                _logger.info(f"    Filtered lines found: {len(invoice_lines)}")
                
                if invoice_lines:
                    _logger.info(f"    Found {len(invoice_lines)} matching line(s)")
                    
                    for idx, inv_line in enumerate(invoice_lines, 1):
                        _logger.info(f"\n    Invoice Line #{idx}:")
                        _logger.info(f"      Product: {inv_line.product_id.display_name}")
                        _logger.info(f"      Quantity: {inv_line.quantity}")
                        _logger.info(f"      Price Unit (base): {inv_line.price_unit}")
                        
                        # Check if custom pricing module is available on invoice line
                        inv_has_custom = hasattr(inv_line, 'use_custom_pricing')
                        inv_has_net_price = hasattr(inv_line, 'net_price')
                        
                        if inv_has_custom and inv_line.use_custom_pricing:
                            _logger.info(f"      ✓ Custom Pricing Detected")
                            if inv_has_net_price:
                                _logger.info(f"      Net Price: {inv_line.net_price}")
                            if hasattr(inv_line, 'applied_discount'):
                                _logger.info(f"      Discount Applied: {inv_line.applied_discount}%")
                            if hasattr(inv_line, 'applied_freight'):
                                _logger.info(f"      Freight Applied: {inv_line.applied_freight}%")
                        
                        # Calculate tax information
                        tax_names = ', '.join(inv_line.tax_ids.mapped('name')) if inv_line.tax_ids else 'No taxes'
                        tax_amount_line = inv_line.price_total - inv_line.price_subtotal
                        
                        _logger.info(f"      Taxes: {tax_names}")
                        _logger.info(f"      Tax Amount: {tax_amount_line}")
                        
                        # Log both amounts for comparison
                        _logger.info(f"      💰 price_subtotal (WITHOUT tax): {inv_line.price_subtotal}")
                        _logger.info(f"      💰 price_total (WITH tax): {inv_line.price_total} ⬅️ USING THIS")
                        
                        # Use price_total (includes tax) for consistency with POS
                        line_amount = inv_line.price_total
                        total_amount += line_amount
                        
                        _logger.info(f"      ✓ Line Contribution: {line_amount}")
                else:
                    _logger.warning(f"    ⚠️ NO MATCHING LINES in bill {bill.name}")
                    _logger.warning(f"       Expected product ID: {move.product_id.id}")
                    _logger.warning(f"       Expected product name: {move.product_id.display_name}")
            
            if total_amount > 0:
                amount_source = "Posted Bills (Actual Invoice)"
                _logger.info(f"\n  ✓ Total from Bills (WITH tax): {total_amount}")
                _logger.info(f"  📊 Source: {amount_source}")
            else:
                _logger.warning("  ⚠️ Bills exist but no matching lines found, falling back to PO")
        # ============================================================================
        # STEP 7: FALLBACK TO PURCHASE ORDER AMOUNTS (IF NO BILLS)
        # ============================================================================
        if total_amount == 0.0:
            _logger.info("-" * 80)
            _logger.info("CALCULATING FROM PURCHASE ORDER (APPROVED AMOUNTS):")
            _logger.info(f"  Reason: {'No posted bills exist' if not posted_bills else 'No matching lines in bills'}")
            
            _logger.info(f"\n  Purchase Order Line Details:")
            _logger.info(f"    Product: {purchase_line.product_id.display_name}")
            _logger.info(f"    Quantity Ordered: {purchase_line.product_qty}")
            _logger.info(f"    Price Unit: {purchase_line.price_unit}")
            
            # Check for custom pricing in PO line
            if use_custom_pricing and has_net_price_field:
                _logger.info(f"    ✓ Custom Pricing Active")
                _logger.info(f"    Net Price: {purchase_line.net_price}")
                _logger.info(f"    Discount: {getattr(purchase_line, 'applied_discount', 0.0)}%")
                _logger.info(f"    Freight: {getattr(purchase_line, 'applied_freight', 0.0)}%")
            
            # Calculate tax information
            tax_names = ', '.join(purchase_line.taxes_id.mapped('name')) if purchase_line.taxes_id else 'No taxes'
            po_tax_amount = purchase_line.price_total - purchase_line.price_subtotal
            
            _logger.info(f"    Taxes: {tax_names}")
            _logger.info(f"    Tax Amount: {po_tax_amount}")
            
            # Log both amounts for comparison
            _logger.info(f"    💰 price_subtotal (WITHOUT tax): {purchase_line.price_subtotal}")
            _logger.info(f"    💰 price_total (WITH tax): {purchase_line.price_total} ⬅️ USING THIS")
            
            # Use price_total for consistency with POS and bills
            total_amount = purchase_line.price_total
            amount_source = f"Purchase Order (State: {purchase_order.state})"
            
            _logger.info(f"\n  ✓ Total from PO (WITH tax): {total_amount}")
            _logger.info(f"  📊 Source: {amount_source}")
        
        # ============================================================================
        # STEP 8: CALCULATE UNIT PRICE
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("CALCULATING UNIT PRICE:")
        
        unit_price = total_amount / qty if qty else 0.0
        
        _logger.info(f"  Formula: total_amount / quantity")
        _logger.info(f"  Calculation: {total_amount} / {qty}")
        _logger.info(f"  ✓ Unit Price (WITH tax): {unit_price}")
        
        # Calculate what it would be WITHOUT tax for comparison
        if posted_bills:
            # Get subtotal from bills
            total_without_tax = sum(
                line.price_subtotal
                for bill in posted_bills
                for line in bill.invoice_line_ids.filtered(
                    lambda l: l.product_id == move.product_id and not l.display_type
                )
            )
        else:
            # Get subtotal from PO
            total_without_tax = purchase_line.price_subtotal
        
        unit_price_without_tax = total_without_tax / qty if qty else 0.0
        tax_amount = total_amount - total_without_tax
        
        _logger.info(f"  ℹ️ For comparison:")
        _logger.info(f"     Total WITHOUT tax: {total_without_tax}")
        _logger.info(f"     Total Tax Amount: {tax_amount}")
        _logger.info(f"     Unit Price WITHOUT tax: {unit_price_without_tax}")
        
        # ============================================================================
        # STEP 9: VALIDATION CHECKS
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("VALIDATION CHECKS:")
        
        # Initialize effective_tax_rate (used later in validation)
        effective_tax_rate = 0.0
        
        # Check if amounts are reasonable
        if total_amount < 0:
            if purchase_order.invoice_ids.filtered(lambda inv: inv.move_type == 'in_refund'):
                _logger.info("✓ Negative amount is expected (Vendor Refund)")
            else:
                _logger.warning("⚠️ NEGATIVE AMOUNT DETECTED")
                _logger.warning(f"   Total Amount: {total_amount}")
                _logger.warning("   This might indicate a return or data issue")
        
        if unit_price < 0:
            _logger.warning("⚠️ NEGATIVE UNIT PRICE DETECTED")
            _logger.warning(f"   Unit Price: {unit_price}")
        
        # Check if quantity matches
        expected_qty = purchase_line.product_qty
        if abs(expected_qty - qty) > 0.01:
            _logger.warning("⚠️ QUANTITY MISMATCH")
            _logger.warning(f"   PO Ordered Qty: {expected_qty}")
            _logger.warning(f"   Stock Move Qty: {qty}")
            _logger.warning("   This might indicate partial delivery or split orders")
        else:
            _logger.info(f"  ✓ Quantity Match: PO qty ({expected_qty}) = Move qty ({qty})")
        
        # Validate tax rate if applicable
        if tax_amount > 0 and total_without_tax > 0:
            effective_tax_rate = (tax_amount / total_without_tax) * 100
            _logger.info(f"  Effective Tax Rate: {effective_tax_rate:.2f}%")
            
            # Kenya standard VAT is 16%
            if abs(effective_tax_rate - 16.0) > 1.0:
                _logger.warning(f"  ⚠️ Tax rate ({effective_tax_rate:.2f}%) differs from standard Kenya VAT (16%)")
        
        # Check if custom pricing was properly applied
        if use_custom_pricing and has_net_price_field:
            expected_net_price = purchase_line.net_price
            if expected_net_price > 0:
                # Calculate expected total with tax
                expected_subtotal = expected_net_price * qty
                expected_total_with_tax = expected_subtotal * (1 + (effective_tax_rate / 100 if tax_amount > 0 else 0))
                
                if abs(total_amount - expected_total_with_tax) > 1.0:
                    _logger.warning("  ⚠️ CUSTOM PRICING MISMATCH")
                    _logger.warning(f"     Expected Total: {expected_total_with_tax}")
                    _logger.warning(f"     Actual Total: {total_amount}")
        
        # ============================================================================
        # STEP 10: FINAL RESULT
        # ============================================================================
        _logger.info("-" * 80)
        _logger.info("FINAL RESULT:")
        _logger.info(f"  ✅ Total Amount (INCLUDING tax): {total_amount}")
        _logger.info(f"  ✅ Unit Price (INCLUDING tax): {unit_price}")
        _logger.info(f"  📊 Data Source: {amount_source}")
        _logger.info(f"  💰 Custom Pricing: {'Yes' if use_custom_pricing else 'No'}")
        _logger.info(f"  📋 This will appear in Stock Card Report as:")
        _logger.info(f"     Purchase Unit Price: {unit_price:.2f}")
        _logger.info(f"     Purchase Amount: {total_amount:.2f}")
        _logger.info("PURCHASE AMOUNT RETRIEVAL - COMPLETE")
        _logger.info("=" * 80)
        
        # Return the tuple
        return (total_amount, unit_price)

    def _prepare_move_data(self, move, location_ids):
        """Prepare data dictionary for a single move - UPDATED with enhanced pricing"""
        _logger.info(f"PREPARING MOVE DATA: {move.id} | {move.reference}")
        
        qty_in = 0.0
        qty_out = 0.0
        location_name = ''
        
        is_dest_in_locations = move.location_dest_id.id in location_ids
        is_source_in_locations = move.location_id.id in location_ids
        
        _logger.info(f"  Source location: {move.location_id.complete_name} (in locations: {is_source_in_locations})")
        _logger.info(f"  Dest location: {move.location_dest_id.complete_name} (in locations: {is_dest_in_locations})")
        
        if is_dest_in_locations and not is_source_in_locations:
            qty_in = move.quantity
            location_name = move.location_dest_id.complete_name
            _logger.info(f"  → IN movement: +{qty_in} to {location_name}")
            
        elif is_source_in_locations and not is_dest_in_locations:
            qty_out = move.quantity
            location_name = move.location_id.complete_name
            _logger.info(f"  → OUT movement: -{qty_out} from {location_name}")
            
        elif is_dest_in_locations and is_source_in_locations:
            if self.show_internal_transfers:
                qty_out = move.quantity
                qty_in = move.quantity
                location_name = f"{move.location_id.name} → {move.location_dest_id.name}"
                _logger.info(f"  → INTERNAL TRANSFER: {qty_in} from {move.location_id.name} to {move.location_dest_id.name}")
            else:
                _logger.info("  → SKIPPING internal transfer (option disabled)")
                return None
        else:
            _logger.info("  → SKIPPING - move doesn't affect selected locations")
            return None
        
        layer = move.stock_valuation_layer_ids[:1] if move.stock_valuation_layer_ids else None
        unit_cost = layer.unit_cost if layer else 0.0
        value = layer.value if layer else 0.0
        
        _logger.info(f"  Valuation layer - Unit cost: {unit_cost}, Value: {value}")
        
        # Get purchase data using enhanced method
        purchase_amount, purchase_unit_price = self._get_purchase_amount_and_unit_price(move)
        
        # Get POS data using enhanced method
        pos_amount, pos_unit_price = self._get_pos_amount_and_unit_price(move)
        
        # Determine move type
        move_type = self._determine_move_type(move)
        _logger.info(f"  Move type: {move_type}")
        
        # Get partner
        partner_name = ''
        if move.partner_id:
            partner_name = move.partner_id.name
        elif move.picking_id and move.picking_id.partner_id:
            partner_name = move.picking_id.partner_id.name
        elif move.purchase_line_id and move.purchase_line_id.order_id.partner_id:
            partner_name = move.purchase_line_id.order_id.partner_id.name
        
        # Get reference
        reference = move.reference or (move.picking_id.name if move.picking_id else move.name)
        
        move_data = {
            'date': move.date,
            'reference': reference,
            'move_type': move_type,
            'partner': partner_name,
            'qty_in': qty_in,
            'qty_out': qty_out,
            'unit_cost': unit_cost,
            'value': value,
            'purchase_unit_price': purchase_unit_price,
            'purchase_amount': purchase_amount,
            'pos_unit_price': pos_unit_price,
            'pos_amount': pos_amount,
            'location': location_name,
            'move': move,
        }
        
        _logger.info(f"  Final move data: IN={qty_in}, OUT={qty_out}, Type={move_type}")
        _logger.info(f"  Purchase Data: Amount={purchase_amount}, Unit Price={purchase_unit_price}")
        _logger.info(f"  POS Data: Amount={pos_amount}, Unit Price={pos_unit_price}")
        return move_data

    def _determine_move_type(self, move):
        """Determine the type of stock move"""
        if move.purchase_line_id:
            if move.origin_returned_move_id:
                return 'Purchase Return'
            return 'Purchase'
        
        if move.picking_id and move.picking_id.pos_order_id:
            return 'POS Sale'
        
        if move.sale_line_id:
            if move.origin_returned_move_id:
                return 'Sales Return'
            return 'Sale'
        
        if move.raw_material_production_id:
            return 'MO Consumption'
        
        if move.production_id:
            return 'MO Production'
        
        if move.scrapped:
            return 'Scrap'
        
        if move.picking_id and move.picking_id.picking_type_id.code == 'inventory':
            return 'Inventory Adjustment'
        
        if move.location_id.usage == 'internal' and move.location_dest_id.usage == 'internal':
            return 'Internal Transfer'
        
        return 'Other'

    def _calculate_running_totals(self, moves_data, opening):
        """Calculate running totals for all moves"""
        _logger.info("CALCULATING RUNNING TOTALS")
        _logger.info(f"Starting with opening - Qty: {opening['qty']}, Value: {opening['value']}")
        
        balance_qty = opening['qty']
        running_value = opening['value']
        running_purchase = opening['purchase_total']
        running_pos = opening['pos_total']
        
        for i, move_data in enumerate(moves_data):
            balance_qty += move_data['qty_in'] - move_data['qty_out']
            running_value += move_data['value']
            running_purchase += move_data['purchase_amount']
            running_pos += move_data['pos_amount']
            
            move_data['balance_qty'] = balance_qty
            move_data['running_value'] = running_value
            move_data['running_purchase'] = running_purchase
            move_data['running_pos'] = running_pos
            
            _logger.info(f"Move {i+1}: IN={move_data['qty_in']}, OUT={move_data['qty_out']}, Balance={balance_qty}, Running Value={running_value}")
        
        _logger.info(f"Final running total - Qty: {balance_qty}, Value: {running_value}")
        return moves_data

    def _calculate_closing(self, moves_with_totals, opening):
        """Calculate closing balance"""
        if moves_with_totals:
            last_move = moves_with_totals[-1]
            closing = {
                'qty': last_move['balance_qty'],
                'value': last_move['running_value'],
                'total_purchases': last_move['running_purchase'],
                'total_pos': last_move['running_pos'],
            }
            _logger.info(f"Closing from last move: Qty={closing['qty']}, Value={closing['value']}")
        else:
            closing = opening.copy()
            _logger.info(f"Closing same as opening: Qty={closing['qty']}, Value={closing['value']}")
        
        return closing

    def _create_excel_report(self, workbook, data):
        """Create Excel workbook with stock card data"""
        _logger.info("CREATING EXCEL REPORT")
        _logger.info(f"Products to export: {len(data['products_data'])}")
        
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#e9ecef',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
        })
        
        opening_format = workbook.add_format({
            'bold': True,
            'bg_color': '#fff3cd',
            'border': 1,
        })
        
        closing_format = workbook.add_format({
            'bold': True,
            'border': 1,
            'top': 2,
        })
        
        number_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        qty_format = workbook.add_format({'num_format': '#,##0.000', 'border': 1})
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
        text_format = workbook.add_format({'border': 1})
        
        purchase_price_format = workbook.add_format({
            'num_format': '#,##0.00',
            'bg_color': '#E7F3FF',
            'border': 1,
        })
        
        pos_price_format = workbook.add_format({
            'num_format': '#,##0.00',
            'bg_color': '#E8F5E9',
            'border': 1,
        })
        
        summary_sheet = workbook.add_worksheet('Summary')
        self._create_summary_sheet(summary_sheet, data, header_format, number_format)
        
        for product_data in data['products_data']:
            sheet_name = product_data['product'].default_code or product_data['product'].name
            sheet_name = sheet_name[:31]
            worksheet = workbook.add_worksheet(sheet_name)
            
            self._create_product_sheet(
                worksheet, product_data, data,
                header_format, opening_format, closing_format,
                number_format, qty_format, date_format, text_format,
                purchase_price_format, pos_price_format
            )

    def _create_summary_sheet(self, worksheet, data, header_format, number_format):
        """Create summary sheet in Excel"""
        row = 0
        
        worksheet.write(row, 0, 'Stock Card Report - Summary', header_format)
        row += 2
        
        worksheet.write(row, 0, 'Date From:', header_format)
        worksheet.write(row, 1, str(data['date_from']))
        row += 1
        
        worksheet.write(row, 0, 'Date To:', header_format)
        worksheet.write(row, 1, str(data['date_to']))
        row += 2
        
        worksheet.write(row, 0, 'Product', header_format)
        worksheet.write(row, 1, 'Opening Qty', header_format)
        worksheet.write(row, 2, 'Closing Qty', header_format)
        worksheet.write(row, 3, 'Opening Value', header_format)
        worksheet.write(row, 4, 'Closing Value', header_format)
        row += 1
        
        for product_data in data['products_data']:
            worksheet.write(row, 0, product_data['product'].display_name)
            worksheet.write(row, 1, product_data['opening']['qty'], number_format)
            worksheet.write(row, 2, product_data['closing']['qty'], number_format)
            worksheet.write(row, 3, product_data['opening']['value'], number_format)
            worksheet.write(row, 4, product_data['closing']['value'], number_format)
            row += 1
        
        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:E', 15)

    def _create_product_sheet(self, worksheet, product_data, data,
                             header_format, opening_format, closing_format,
                             number_format, qty_format, date_format, text_format,
                             purchase_price_format, pos_price_format):
        """Create individual product sheet in Excel"""
        row = 0
        
        worksheet.write(row, 0, f"Product: {product_data['product'].display_name}", header_format)
        row += 1
        worksheet.write(row, 0, f"Period: {data['date_from']} to {data['date_to']}")
        row += 2
        
        headers = [
            'Date', 'Reference', 'Type', 'Partner',
            'In', 'Out', 'Balance', 'Unit Cost', 'Value', 'Running Value',
            'Purch Unit Price', 'Purchase Amt', 'Running Purch',
            'POS Unit Price', 'POS Amt', 'Running POS'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1
        
        worksheet.write(row, 0, 'Opening Balance', opening_format)
        worksheet.write(row, 1, '', opening_format)
        worksheet.write(row, 2, '', opening_format)
        worksheet.write(row, 3, '', opening_format)
        worksheet.write(row, 4, '', opening_format)
        worksheet.write(row, 5, '', opening_format)
        worksheet.write(row, 6, product_data['opening']['qty'], opening_format)
        worksheet.write(row, 7, product_data['opening']['unit_cost'], opening_format)
        worksheet.write(row, 8, '', opening_format)
        worksheet.write(row, 9, product_data['opening']['value'], opening_format)
        worksheet.write(row, 10, '', opening_format)
        worksheet.write(row, 11, '', opening_format)
        worksheet.write(row, 12, product_data['opening']['purchase_total'], opening_format)
        worksheet.write(row, 13, '', opening_format)
        worksheet.write(row, 14, '', opening_format)
        worksheet.write(row, 15, product_data['opening']['pos_total'], opening_format)
        row += 1
        
        for move in product_data['moves']:
            worksheet.write(row, 0, move['date'], date_format)
            worksheet.write(row, 1, move['reference'], text_format)
            worksheet.write(row, 2, move['move_type'], text_format)
            worksheet.write(row, 3, move['partner'], text_format)
            worksheet.write(row, 4, move['qty_in'] if move['qty_in'] else '', qty_format)
            worksheet.write(row, 5, move['qty_out'] if move['qty_out'] else '', qty_format)
            worksheet.write(row, 6, move['balance_qty'], qty_format)
            worksheet.write(row, 7, move['unit_cost'], number_format)
            worksheet.write(row, 8, move['value'], number_format)
            worksheet.write(row, 9, move['running_value'], number_format)
            worksheet.write(row, 10, move['purchase_unit_price'] if move['purchase_unit_price'] else '', purchase_price_format)
            worksheet.write(row, 11, move['purchase_amount'] if move['purchase_amount'] else '', number_format)
            worksheet.write(row, 12, move['running_purchase'], number_format)
            worksheet.write(row, 13, move['pos_unit_price'] if move['pos_unit_price'] else '', pos_price_format)
            worksheet.write(row, 14, move['pos_amount'] if move['pos_amount'] else '', number_format)
            worksheet.write(row, 15, move['running_pos'], number_format)
            row += 1
        
        worksheet.write(row, 0, 'Closing Balance', closing_format)
        worksheet.write(row, 1, '', closing_format)
        worksheet.write(row, 2, '', closing_format)
        worksheet.write(row, 3, '', closing_format)
        worksheet.write(row, 4, '', closing_format)
        worksheet.write(row, 5, '', closing_format)
        worksheet.write(row, 6, product_data['closing']['qty'], closing_format)
        worksheet.write(row, 7, '', closing_format)
        worksheet.write(row, 8, '', closing_format)
        worksheet.write(row, 9, product_data['closing']['value'], closing_format)
        worksheet.write(row, 10, '', closing_format)
        worksheet.write(row, 11, '', closing_format)
        worksheet.write(row, 12, product_data['closing']['total_purchases'], closing_format)
        worksheet.write(row, 13, '', closing_format)
        worksheet.write(row, 14, '', closing_format)
        worksheet.write(row, 15, product_data['closing']['total_pos'], closing_format)
        
        worksheet.set_column('A:A', 12)
        worksheet.set_column('B:B', 18)
        worksheet.set_column('C:C', 18)
        worksheet.set_column('D:D', 20)
        worksheet.set_column('E:G', 12)
        worksheet.set_column('H:P', 14)
        
        worksheet.freeze_panes(4, 0)