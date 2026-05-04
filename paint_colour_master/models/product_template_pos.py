from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """
    Inherit product.template model to enforce POS availability for standard products.
    Loyalty program products are excluded from POS validation.
    Enhanced with comprehensive logging and debugging.
    """
    _inherit = 'product.template'
    
    # Keep existing stored Boolean field - DO NOT CHANGE TYPE
    available_on_pos = fields.Boolean(
        string='Available on POS (Indexed)',
        default=True,
        index=True,
        help='Indexed field - Indicates if this product is available for sale through the Point of Sale.'
    )
    
    def _is_loyalty_product(self, vals=None, record=None):
        """
        Determine if the product is a loyalty program product.
        Loyalty products should bypass POS availability validation.
        
        Args:
            vals (dict, optional): Product creation/update values
            record (product.template, optional): Existing product record
            
        Returns:
            bool: True if product is identified as a loyalty product
        """
        product_name = ''
        
        # Check from creation values
        if vals and 'name' in vals:
            product_name = vals.get('name', '').lower()
        # Check from existing record
        elif record and record.name:
            product_name = record.name.lower()
        else:
            _logger.debug("🔍 POS Validation: Insufficient data for loyalty detection")
            return False
        
        # Loyalty product keywords
        loyalty_keywords = [
            'loyalty', 'reward', 'point', 'coupon', 'gift', 'voucher', 
            'promo', 'discount', 'bonus', 'credit', 'benefit'
        ]
        
        # Check name patterns
        if any(keyword in product_name for keyword in loyalty_keywords):
            _logger.info("🎯 POS Validation: Identified as loyalty product by name pattern: %s", product_name)
            return True
        
        # Check context flags
        if self.env.context.get('loyalty_program_creation'):
            _logger.info("🎯 POS Validation: Identified as loyalty product by context flag: %s", product_name)
            return True
            
        # Check product flags combination (common for loyalty products)
        if vals:
            sale_ok = vals.get('sale_ok', True)
            purchase_ok = vals.get('purchase_ok', True)
            if not sale_ok and not purchase_ok:
                _logger.info("🎯 POS Validation: Identified as loyalty product by flag combination: %s", product_name)
                return True
        elif record:
            if not record.sale_ok and not record.purchase_ok:
                _logger.info("🎯 POS Validation: Identified as loyalty product by flag combination: %s", record.name)
                return True
        
        _logger.debug("❌ POS Validation: Not a loyalty product: %s", product_name)
        return False

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        """
        Override fields_get to ensure available_on_pos is properly defined for frontend.
        This prevents OwlError by providing complete field metadata.
        """
        _logger.debug("📋 POS Fields Get: Generating field metadata for frontend")
        
        fields = super(ProductTemplate, self).fields_get(allfields, attributes)
        
        # Ensure available_on_pos has complete metadata for frontend
        if 'available_on_pos' in fields:
            fields['available_on_pos'].update({
                'type': 'boolean',
                'string': 'Available on POS (Indexed)',
                'store': True,
                'searchable': True,
                'sortable': True,
                'readonly': False,
            })
            _logger.debug("✅ POS Fields Get: Enhanced available_on_pos field metadata")
        
        _logger.debug("✅ POS Fields Get: Field metadata generation completed")
        return fields

    @api.constrains('available_in_pos')
    def _check_available_in_pos_required(self):
        """
        Ensure the standard 'Available in POS' field is always checked for standard products.
        Loyalty products are excluded from this constraint.
        """
        _logger.debug("🔍 POS Constraint: Checking %s products for POS availability", len(self))
        
        validation_summary = self._get_validation_summary("constraint")
        
        for record in self:
            product_name = record.name or f"ID_{record.id}"
            
            # Skip validation for loyalty products
            if self._is_loyalty_product(record=record):
                _logger.info("🎯 POS Constraint: Skipping POS validation for loyalty product: %s", product_name)
                continue
                
            # Apply validation for standard products
            if not record.available_in_pos:
                _logger.warning("🚫 POS Constraint: Standard product '%s' has Available in POS unchecked", product_name)
                raise ValidationError(
                    "Product must be 'Available in POS'. "
                    "Please check the 'Available in POS' checkbox before saving."
                )
            
            _logger.debug("✅ POS Constraint: Validation passed for standard product: %s", product_name)
        
        _logger.debug("✅ POS Constraint: All constraints processed successfully")

    @api.model_create_multi
    def create(self, vals_list):
        """
        Set defaults and validate during product creation.
        Loyalty products bypass POS availability validation.
        Enhanced with field synchronization and comprehensive logging.
        """
        _logger.info("🛠️ POS Creation: Starting creation of %s product template(s)", len(vals_list))
        
        processed_vals = []
        for idx, vals in enumerate(vals_list):
            product_name = vals.get('name', f'Product_{idx}')
            
            # Ensure available_on_pos always has a value to prevent frontend errors
            if 'available_on_pos' not in vals:
                # Sync with available_in_pos or default to True
                available_in_pos = vals.get('available_in_pos', True)
                vals['available_on_pos'] = available_in_pos
                _logger.debug("🔄 POS Creation: Set available_on_pos=%s for product: %s", 
                            available_in_pos, product_name)
            
            # Check if this is a loyalty product
            is_loyalty = self._is_loyalty_product(vals=vals)
            
            if is_loyalty:
                _logger.info("🎯 POS Creation: Processing loyalty product - %s", product_name)
                # For loyalty products, respect their POS settings without validation
                _logger.info("🎯 POS Creation: Loyalty product '%s' - available_in_pos=%s, available_on_pos=%s", 
                           product_name, vals.get('available_in_pos'), vals.get('available_on_pos'))
                
            else:
                _logger.info("🔧 POS Creation: Processing standard product - %s", product_name)
                # For standard products, enforce POS availability
                if 'available_in_pos' not in vals:
                    vals['available_in_pos'] = True
                    _logger.debug("🔧 POS Creation: Set default available_in_pos=True for standard product: %s", product_name)
                
                # Validate: prevent creation if available_in_pos is explicitly False for standard products
                if 'available_in_pos' in vals and not vals['available_in_pos']:
                    _logger.error("🚫 POS Creation: Standard product '%s' cannot have Available in POS unchecked", product_name)
                    raise ValidationError(
                        "Cannot create product with 'Available in POS' unchecked. "
                        "This field must be enabled for standard products."
                    )
                
                _logger.debug("✅ POS Creation: Standard product '%s' validated successfully", product_name)
            
            processed_vals.append(vals)
        
        # Proceed with creation
        try:
            result = super(ProductTemplate, self).create(processed_vals)
            _logger.info("✅ POS Creation: Successfully created %s product template(s)", len(processed_vals))
            
            # Log creation summary
            for product in result:
                product_name = product.name or f"ID_{product.id}"
                _logger.debug("📝 POS Creation: Product '%s' created with available_in_pos=%s, available_on_pos=%s", 
                            product_name, product.available_in_pos, product.available_on_pos)
            
            return result
        except Exception as e:
            _logger.error("❌ POS Creation: Failed to create product templates - %s", e)
            _logger.debug("🔍 POS Creation: Failed values: %s", processed_vals)
            raise

    def write(self, vals):
        """
        Prevent unchecking the 'Available in POS' field during updates for standard products.
        Loyalty products can have their POS availability freely modified.
        Enhanced with field synchronization and comprehensive logging.
        """
        _logger.debug("📝 POS Write: Starting update of %s product template(s)", len(self))
        
        # Log current state before changes
        for record in self:
            product_name = record.name or f"ID_{record.id}"
            _logger.debug("📝 POS Write: Product '%s' current state - available_in_pos=%s, available_on_pos=%s", 
                        product_name, record.available_in_pos, record.available_on_pos)
        
        # Sync available_on_pos with available_in_pos when available_in_pos changes
        if 'available_in_pos' in vals and 'available_on_pos' not in vals:
            vals['available_on_pos'] = vals['available_in_pos']
            _logger.debug("🔄 POS Write: Synced available_on_pos with available_in_pos: %s", vals['available_in_pos'])
        
        # Check if POS availability is being disabled
        if 'available_in_pos' in vals and not vals['available_in_pos']:
            for record in self:
                product_name = record.name or f"ID_{record.id}"
                
                # Skip validation for loyalty products
                if self._is_loyalty_product(record=record):
                    _logger.info("🎯 POS Write: Allowing POS disable for loyalty product: %s", product_name)
                    continue
                    
                # Prevent unchecking for standard products
                _logger.warning("🚫 POS Write: Cannot disable POS for standard product: %s", product_name)
                raise ValidationError(
                    "Cannot uncheck 'Available in POS'. "
                    "Standard products must always be available in POS."
                )
        
        # Proceed with write operation
        try:
            result = super(ProductTemplate, self).write(vals)
            _logger.info("✅ POS Write: Successfully updated %s product template(s)", len(self))
            
            # Log updated state
            for record in self:
                product_name = record.name or f"ID_{record.id}"
                _logger.debug("📝 POS Write: Product '%s' updated state - available_in_pos=%s, available_on_pos=%s", 
                            product_name, record.available_in_pos, record.available_on_pos)
            
            return result
        except Exception as e:
            _logger.error("❌ POS Write: Failed to update product templates - %s", e)
            _logger.debug("🔍 POS Write: Failed values: %s", vals)
            raise

    def _get_validation_summary(self, operation_type="create"):
        """
        Helper method to provide validation summary for debugging.
        
        Args:
            operation_type (str): Type of operation being performed
            
        Returns:
            dict: Validation summary
        """
        summary = {
            'total_products': len(self),
            'loyalty_products': 0,
            'standard_products': 0,
            'operation': operation_type,
            'timestamp': fields.Datetime.now()
        }
        
        for record in self:
            if self._is_loyalty_product(record=record):
                summary['loyalty_products'] += 1
            else:
                summary['standard_products'] += 1
        
        _logger.debug("📊 POS Validation Summary: %s", summary)
        return summary

    @api.model
    def _update_pos_availability_batch(self, product_ids, available_in_pos):
        """
        Batch update POS availability with proper validation.
        Safe method for bulk operations.
        
        Args:
            product_ids (list): List of product IDs to update
            available_in_pos (bool): New POS availability value
            
        Returns:
            dict: Operation results
        """
        _logger.info("🔄 POS Batch Update: Starting batch update for %s products to available_in_pos=%s", 
                    len(product_ids), available_in_pos)
        
        products = self.browse(product_ids)
        results = {
            'successful': 0,
            'skipped_loyalty': 0,
            'failed_standard': 0,
            'total_processed': len(products)
        }
        
        for product in products:
            try:
                product_name = product.name or f"ID_{product.id}"
                
                # Skip loyalty products if disabling POS
                if not available_in_pos and self._is_loyalty_product(record=product):
                    _logger.info("🎯 POS Batch: Skipping loyalty product for POS disable: %s", product_name)
                    results['skipped_loyalty'] += 1
                    continue
                    
                # Prevent disabling POS for standard products
                if not available_in_pos and not self._is_loyalty_product(record=product):
                    _logger.warning("🚫 POS Batch: Cannot disable POS for standard product: %s", product_name)
                    results['failed_standard'] += 1
                    continue
                
                # Perform the update
                product.write({
                    'available_in_pos': available_in_pos,
                    'available_on_pos': available_in_pos
                })
                results['successful'] += 1
                _logger.debug("✅ POS Batch: Updated product: %s to available_in_pos=%s", product_name, available_in_pos)
                
            except Exception as e:
                _logger.error("❌ POS Batch: Failed to update product %s: %s", product_name, e)
                results['failed_standard'] += 1
        
        _logger.info("✅ POS Batch Update Completed: %s", results)
        return results

    def action_sync_pos_fields(self):
        """
        Manual action to sync available_on_pos with available_in_pos for all products.
        Useful for maintenance and debugging.
        """
        _logger.info("🔄 POS Sync: Starting manual sync of POS fields for %s products", len(self))
        
        synced_count = 0
        for product in self:
            if product.available_on_pos != product.available_in_pos:
                old_value = product.available_on_pos
                product.available_on_pos = product.available_in_pos
                synced_count += 1
                _logger.debug("🔄 POS Sync: Product '%s' synced from %s to %s", 
                            product.name, old_value, product.available_in_pos)
        
        _logger.info("✅ POS Sync: Completed - %s products synchronized", synced_count)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'POS Fields Sync',
                'message': f'Successfully synchronized {synced_count} products',
                'type': 'success',
                'sticky': False,
            }
        }