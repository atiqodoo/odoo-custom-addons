# -*- coding: utf-8 -*-
from odoo import models, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """
    Inherit product.template model to enforce Unit of Measure (UoM) selection.
    Excludes loyalty program products and tinting products from UoM validation.
    """
    _inherit = 'product.template'

    def _is_loyalty_product(self, vals):
        """
        Determine if the product template being created is for loyalty programs.
        Loyalty programs automatically create internal products that should bypass UoM validation.
        
        Args:
            vals (dict): Product template creation values
            
        Returns:
            bool: True if product is identified as a loyalty product
        """
        product_name = vals.get('name', '').lower()
        
        # Check for loyalty-related keywords in product name
        loyalty_keywords = ['loyalty', 'reward', 'point', 'coupon', 'gift', 'voucher', 'promo']
        if any(keyword in product_name for keyword in loyalty_keywords):
            _logger.info("✅ UoM Validation: Identified as loyalty product by name keyword: %s", product_name)
            return True
        
        # Check product type flags - loyalty products are typically not for sale/purchase
        is_sale_ok = vals.get('sale_ok', True)
        is_purchase_ok = vals.get('purchase_ok', True)
        available_in_pos = vals.get('available_in_pos', False)
        
        # Loyalty products often have specific flag combinations
        if not is_sale_ok and not is_purchase_ok and available_in_pos:
            _logger.info("✅ UoM Validation: Identified as loyalty product by flag combination - sale_ok=%s, purchase_ok=%s, available_in_pos=%s", 
                        is_sale_ok, is_purchase_ok, available_in_pos)
            return True
            
        # Check for specific product types used in loyalty programs
        product_type = vals.get('type', 'service')
        if product_type == 'service' and not is_sale_ok and available_in_pos:
            _logger.info("✅ UoM Validation: Identified as loyalty service product - type=%s, sale_ok=%s, available_in_pos=%s", 
                        product_type, is_sale_ok, available_in_pos)
            return True
            
        # Check context for loyalty program creation
        if self.env.context.get('loyalty_program_creation'):
            _logger.info("✅ UoM Validation: Identified as loyalty product by context flag")
            return True
            
        # Check for default loyalty program naming patterns
        default_loyalty_patterns = [
            'loyalty',
            'reward',
            'point',
            'coupon',
            'gift',
            'promo',
            'discount'
        ]
        
        if any(pattern in product_name for pattern in default_loyalty_patterns):
            _logger.info("✅ UoM Validation: Identified as loyalty product by default pattern: %s", product_name)
            return True
            
        # Check if created through specific modules
        module_origin = self.env.context.get('module', '')
        if 'loyalty' in module_origin.lower() or 'point_of_sale' in module_origin.lower():
            _logger.info("✅ UoM Validation: Identified as loyalty product by module origin: %s", module_origin)
            return True
            
        _logger.debug("❌ UoM Validation: Not identified as loyalty product: %s", product_name)
        return False

    def _is_tinting_product(self, vals):
        """
        Determine if the product is being created by the tinting wizard.
        Tinting products should bypass UoM validation constraints.
        
        Args:
            vals (dict): Product template creation values
            
        Returns:
            bool: True if product is identified as a tinting product
        """
        # Check context for tinting operation
        if self.env.context.get('tinting_operation'):
            _logger.info("🎯 UoM Validation: Identified as tinting product by context flag")
            return True
        
        # Check product flags for tinting products
        is_tinted_product = vals.get('is_tinted_product', False)
        if is_tinted_product:
            _logger.info("🎯 UoM Validation: Identified as tinting product by flag")
            return True
            
        # Check naming pattern for tinted products
        product_name = vals.get('name', '').lower()
        tinting_keywords = ['tint', 'tinted', 'colour', 'color', 'paint', 'base']
        if any(keyword in product_name for keyword in tinting_keywords):
            _logger.info("🎯 UoM Validation: Identified as tinting product by name pattern: %s", product_name)
            return True
            
        # Check if created through paint tinting module
        module_origin = self.env.context.get('module', '')
        if 'paint_tinting' in module_origin.lower() or 'tinting' in module_origin.lower():
            _logger.info("🎯 UoM Validation: Identified as tinting product by module origin: %s", module_origin)
            return True
            
        # Check for colour code and fandeck associations (common in tinting products)
        if vals.get('colour_code_id') or vals.get('fandeck_id'):
            _logger.info("🎯 UoM Validation: Identified as tinting product by colour/fandeck association")
            return True
            
        _logger.debug("❌ UoM Validation: Not identified as tinting product: %s", product_name)
        return False

    def _validate_uom_required(self, vals, operation_type="create"):
        """
        Validate that UoM is provided for non-loyalty and non-tinting products.
        
        Args:
            vals (dict): Values being used for create/write operation
            operation_type (str): Type of operation - 'create' or 'write'
            
        Raises:
            ValidationError: If UoM validation fails for standard products
        """
        product_name = vals.get('name', 'Unknown Product')
        
        # Skip UoM validation for loyalty products
        if self._is_loyalty_product(vals):
            _logger.info("🎯 UoM Validation: Skipping UoM check for loyalty product: %s", product_name)
            return True
            
        # Skip UoM validation for tinting products
        if self._is_tinting_product(vals):
            _logger.info("🎯 UoM Validation: Skipping UoM check for tinting product: %s", product_name)
            return True
            
        # Check if UoM is provided in the values
        uom_id = vals.get('uom_id')
        if not uom_id:
            _logger.warning("🚫 UoM Validation: No UoM provided for %s operation on product: %s", 
                          operation_type, product_name)
            raise ValidationError(_("Please select a Unit of Measure (UoM) before saving the product."))
        
        _logger.debug("✅ UoM Validation: UoM check passed for %s: %s", product_name, uom_id)
        return True

    @api.model
    def create(self, vals):
        """
        Create a product template with UoM validation for non-loyalty and non-tinting products.
        
        Args:
            vals (dict): Product template creation values
            
        Returns:
            product.template: Created product template record
            
        Raises:
            ValidationError: If UoM validation fails for standard products
        """
        product_name = vals.get('name', 'New Product Template')
        _logger.info("🛠️ UoM: Starting product template creation for: %s", product_name)

        # Validate UoM for standard products only (skip for loyalty and tinting products)
        if not self._is_loyalty_product(vals) and not self._is_tinting_product(vals):
            _logger.debug("🔧 UoM: Validating UoM for standard product: %s", product_name)
            self._validate_uom_required(vals, "create")
        else:
            skip_reason = "loyalty product" if self._is_loyalty_product(vals) else "tinting product"
            _logger.info("🎯 UoM: Skipping UoM validation for %s: %s", skip_reason, product_name)

        # Proceed with creation
        try:
            result = super(ProductTemplate, self).create(vals)
            _logger.info("✅ UoM: Product template created successfully: %s (ID: %s)", product_name, result.id)
            return result
        except Exception as e:
            _logger.error("❌ UoM: Failed to create product template '%s': %s", product_name, e)
            raise

    def write(self, vals):
        """
        Write to product template with UoM validation for non-loyalty and non-tinting products.
        
        Args:
            vals (dict): Values to update
            
        Returns:
            bool: True if write operation succeeds
            
        Raises:
            ValidationError: If UoM validation fails for standard products
        """
        _logger.debug("📝 UoM: Starting write operation on %s product templates", len(self))

        for record in self:
            product_name = record.name or f"ID_{record.id}"
            
            # Skip UoM validation for loyalty products
            if self._is_loyalty_product({'name': product_name}):
                _logger.debug("🎯 UoM: Skipping UoM validation for loyalty product during write: %s", product_name)
                continue
                
            # Skip UoM validation for tinting products
            # Use hasattr guard: is_tinted_product belongs to paint_colour_master
            # which may not be loaded during module upgrades or in other environments
            is_tinted = record.is_tinted_product if 'is_tinted_product' in record._fields else False
            if self._is_tinting_product({'name': product_name, 'is_tinted_product': is_tinted}):
                _logger.debug("🎯 UoM: Skipping UoM validation for tinting product during write: %s", product_name)
                continue
                
            _logger.debug("🔧 UoM: Validating UoM for standard product during write: %s", product_name)
            
            # If UoM is being explicitly set to False/None
            if 'uom_id' in vals and not vals.get('uom_id'):
                _logger.warning("🚫 UoM: Attempt to set empty UoM for product during write: %s", product_name)
                raise ValidationError(_("Please select a Unit of Measure (UoM) before saving the product."))
            
            # If we're checking existing record and it doesn't have UoM
            current_uom_id = vals.get('uom_id', record.uom_id.id)
            if not current_uom_id:
                _logger.warning("🚫 UoM: Product missing UoM during write operation: %s", product_name)
                raise ValidationError(_("Please select a Unit of Measure (UoM) before saving the product."))

        # Proceed with write operation
        try:
            result = super(ProductTemplate, self).write(vals)
            _logger.info("✅ UoM: Write operation completed successfully for %s product templates", len(self))
            return result
        except Exception as e:
            _logger.error("❌ UoM: Write operation failed for product templates: %s", e)
            raise

    @api.model
    def default_get(self, fields_list):
        """
        Override default values for product template.
        Sets UoM to blank by default but preserves other defaults.
        
        Args:
            fields_list (list): List of fields to get defaults for
            
        Returns:
            dict: Default values for the fields
        """
        _logger.debug("⚙️ UoM: Getting default values for product template")
        
        # Get defaults from parent class
        defaults = super(ProductTemplate, self).default_get(fields_list)
        
        # Check if this might be a loyalty product creation context
        is_loyalty_context = (
            self.env.context.get('loyalty_program_creation') or
            'loyalty' in str(self.env.context).lower()
        )
        
        # Check if this might be a tinting product creation context
        is_tinting_context = (
            self.env.context.get('tinting_operation') or
            'paint_tinting' in str(self.env.context).lower() or
            'tinting' in str(self.env.context).lower()
        )
        
        if is_loyalty_context:
            _logger.info("🎯 UoM: Loyalty context detected in default_get - setting UoM to False")
            # For loyalty products, set UoM to False to allow creation without UoM
            defaults['uom_id'] = False
        elif is_tinting_context:
            _logger.info("🎯 UoM: Tinting context detected in default_get - setting UoM to False")
            # For tinting products, set UoM to False to allow creation without UoM
            defaults['uom_id'] = False
        else:
            _logger.debug("🔧 UoM: Standard product context - setting UoM to False by default")
            # Override default uom_id to be blank for standard products
            # Validation will enforce UoM selection during create/write
            defaults['uom_id'] = False
            
        _logger.debug("✅ UoM: Default values processing completed")
        return defaults

    def _get_loyalty_product_identification_summary(self, vals):
        """
        Helper method to provide detailed logging about loyalty product identification.
        Useful for debugging and understanding how products are classified.
        
        Args:
            vals (dict): Product template values
            
        Returns:
            str: Detailed identification summary
        """
        product_name = vals.get('name', 'Unknown')
        identification_factors = []
        
        # Name pattern analysis
        loyalty_keywords = ['loyalty', 'reward', 'point', 'coupon', 'gift', 'voucher', 'promo']
        found_keywords = [kw for kw in loyalty_keywords if kw in product_name.lower()]
        if found_keywords:
            identification_factors.append(f"name keywords: {found_keywords}")
        
        # Flag analysis
        flags = {
            'sale_ok': vals.get('sale_ok', True),
            'purchase_ok': vals.get('purchase_ok', True),
            'available_in_pos': vals.get('available_in_pos', False),
            'type': vals.get('type', 'service')
        }
        identification_factors.append(f"flags: {flags}")
        
        # Context analysis
        context_info = {
            'loyalty_program_creation': self.env.context.get('loyalty_program_creation'),
            'tinting_operation': self.env.context.get('tinting_operation'),
            'module': self.env.context.get('module', '')
        }
        identification_factors.append(f"context: {context_info}")
        
        return f"Product '{product_name}' analysis: {', '.join(identification_factors)}"

    # Additional constraint method for comprehensive validation
    @api.constrains('uom_id')
    def _check_uom_id(self):
        """
        Constraint method to ensure non-loyalty and non-tinting products have UoM assigned.
        This provides an additional layer of validation.
        """
        _logger.debug("🔍 UoM: Running UoM constraint check on %s product templates", len(self))
        
        for record in self:
            product_name = record.name or f"ID_{record.id}"
            
            # Skip constraint for loyalty products
            if self._is_loyalty_product({'name': product_name}):
                _logger.debug("🎯 UoM: Skipping UoM constraint for loyalty product: %s", product_name)
                continue
                
            # Skip constraint for tinting products
            if self._is_tinting_product({'name': product_name, 'is_tinted_product': record.is_tinted_product}):
                _logger.debug("🎯 UoM: Skipping UoM constraint for tinting product: %s", product_name)
                continue
                
            # Validate UoM for standard products
            if not record.uom_id:
                _logger.warning("🚫 UoM: UoM constraint failed - no UoM assigned to product: %s", product_name)
                raise ValidationError(_("Please select a Unit of Measure (UoM) for the product."))
                
            _logger.debug("✅ UoM: UoM constraint passed for product: %s", product_name)
        
        _logger.debug("✅ UoM: All UoM constraints processed successfully")