# -*- coding: utf-8 -*-
from odoo import models, fields, api
import re
import logging

_logger = logging.getLogger(__name__)

class ProductTemplateNameAuto(models.Model):
    _inherit = 'product.template'

    base_product_name = fields.Char(
        string='Base Product Name',
        help='Product name without colour code or name. This is used to rebuild the full name.',
        store=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to auto-concatenate name with colour name and code.
        Works for both normal product creation AND manufacturing-created products.
        """
        _logger.info("🚀 ProductTemplateNameAuto.create() called")
        _logger.info(f"  Context: {self.env.context}")
        
        # CHECK: Skip auto-naming if context flag is set (for manufacturing products)
        if self.env.context.get('skip_auto_name'):
            _logger.info("🛑 SKIPPING AUTO-NAMING: Context flag 'skip_auto_name' detected")
            _logger.info("  This is likely a manufacturing-created product, using provided name as-is")
            return super().create(vals_list)
        
        _logger.info("✅ PROCEEDING WITH AUTO-NAMING: Normal product creation")
        
        for i, vals in enumerate(vals_list):
            _logger.info(f"  Processing product {i+1}/{len(vals_list)}")
            
            base_name = vals.get('name', '').strip()
            colour_code_id = vals.get('colour_code_id')
            is_tinted_product = vals.get('is_tinted_product', False)
            
            _logger.info(f"    Initial name: '{base_name}'")
            _logger.info(f"    Colour code ID: {colour_code_id}")
            _logger.info(f"    Is tinted product: {is_tinted_product}")
            
            if base_name and colour_code_id:
                _logger.info("    ➡️ Has base name AND colour code - processing auto-naming")
                
                # Strip any existing colour info first
                vals['base_product_name'] = self._strip_colour_info(base_name)
                _logger.info(f"    Base product name extracted: '{vals['base_product_name']}'")
                
                colour_code = self.env['colour.code'].browse(colour_code_id)
                if colour_code and colour_code.code and colour_code.name:
                    _logger.info(f"    Colour code found: {colour_code.code}, Name: {colour_code.name}")
                    
                    # Build the formatted product name
                    new_name = self._build_product_name(vals['base_product_name'], colour_code.code, colour_code.name)
                    vals['name'] = new_name
                    _logger.info(f"    ✅ Created product name: '{new_name}'")
                else:
                    _logger.warning("    ⚠️ Colour code missing code or name, using base name")
                    vals['name'] = vals['base_product_name']
                    
            elif base_name:
                _logger.info("    ➡️ Has base name but no colour code - storing base name only")
                vals['base_product_name'] = self._strip_colour_info(base_name)
                _logger.info(f"    Base product name stored: '{vals['base_product_name']}'")
            else:
                _logger.info("    ➡️ No base name provided - skipping auto-naming")
        
        _logger.info("✅ Product creation with auto-naming completed")
        return super().create(vals_list)

    def write(self, vals):
        """
        Override write to auto-concatenate name with colour name and code on update.
        Works for both normal product updates AND manufacturing-related updates.
        """
        _logger.info("✏️ ProductTemplateNameAuto.write() called")
        _logger.info(f"  Updating {len(self)} product(s)")
        _logger.info(f"  Update values: {list(vals.keys())}")
        _logger.info(f"  Context: {self.env.context}")
        
        # CHECK: Skip auto-naming if context flag is set
        if self.env.context.get('skip_auto_name'):
            _logger.info("🛑 SKIPPING AUTO-NAMING: Context flag 'skip_auto_name' detected")
            _logger.info("  This is likely a manufacturing-related update, using provided values as-is")
            return super().write(vals)
        
        _logger.info("✅ PROCEEDING WITH AUTO-NAMING: Normal product update")
        
        for record in self:
            _logger.info(f"  Processing product: {record.name} (ID: {record.id})")
            
            base_name = vals.get('name', record.base_product_name or record.name or '').strip()
            _logger.info(f"    Current name: '{record.name}'")
            _logger.info(f"    Base product name: '{record.base_product_name}'")
            _logger.info(f"    New base name from vals: '{base_name}'")
            
            if 'name' in vals:
                _logger.info("    ➡️ Name field being updated - processing")
                # Strip colour info using the current colour code record
                current_colour = self.env['colour.code'].browse(vals.get('colour_code_id', record.colour_code_id.id))
                _logger.info(f"    Current colour: {current_colour.name if current_colour else 'None'}")
                
                base_name = self._strip_colour_info_smart(vals['name'], current_colour)
                vals['base_product_name'] = base_name
                _logger.info(f"    Extracted base product name: '{base_name}'")
            
            if 'colour_code_id' in vals or 'name' in vals:
                _logger.info("    ➡️ Colour code or name changed - rebuilding product name")
                colour_code_id = vals.get('colour_code_id', record.colour_code_id.id)
                _logger.info(f"    Colour code ID: {colour_code_id}")
                
                if colour_code_id:
                    colour_code = self.env['colour.code'].browse(colour_code_id)
                    if colour_code and colour_code.code and colour_code.name:
                        _logger.info(f"    Building name with: Code='{colour_code.code}', Name='{colour_code.name}'")
                        
                        new_name = self._build_product_name(base_name, colour_code.code, colour_code.name)
                        vals['name'] = new_name
                        _logger.info(f"    ✅ Updated product name: '{new_name}'")
                    else:
                        _logger.warning("    ⚠️ Colour code missing code or name, using base name")
                        vals['name'] = base_name
                else:
                    _logger.info("    No colour code ID, using base name")
                    vals['name'] = base_name
            else:
                _logger.info("    ➡️ No relevant fields changed - skipping auto-naming")
        
        _logger.info("✅ Product update with auto-naming completed")
        return super().write(vals)

    def _strip_colour_info(self, name):
        """
        Remove colour code pattern [XXXXX] and colour name from the name.
        Strategy: Only remove the exact colour name if it matches the current colour_code.
        """
        _logger.debug(f"🔄 _strip_colour_info() called with: '{name}'")
        
        if not name:
            _logger.debug("  Empty name provided, returning empty string")
            return ""
        
        # Step 1: Remove colour code pattern [XXXXX]
        cleaned_name = re.sub(r'\s*\[[\w\-]+\]\s*', ' ', name)
        _logger.debug(f"  After code removal: '{cleaned_name}'")
        
        # Step 2: Clean up extra spaces
        cleaned_name = ' '.join(cleaned_name.split())
        _logger.debug(f"  After space cleanup: '{cleaned_name}'")
        
        # Step 3: Try to remove known colour name from the end
        # We'll check if the cleaned name ends with a known colour pattern
        # This is safer than trying to guess which words are colour names
        
        # For now, just remove [CODE] and return
        # The colour name will be added fresh when building
        _logger.debug(f"  Final cleaned name: '{cleaned_name}'")
        return cleaned_name

    def _strip_colour_info_smart(self, name, colour_record):
        """
        Strip colour info using the actual colour record for accuracy.
        """
        _logger.debug(f"🔄 _strip_colour_info_smart() called with: '{name}'")
        _logger.debug(f"  Colour record: {colour_record.name if colour_record else 'None'}")
        
        if not name:
            _logger.debug("  Empty name provided, returning empty string")
            return ""
        
        # Remove [CODE] pattern
        cleaned_name = re.sub(r'\s*\[[\w\-]+\]\s*', ' ', name)
        _logger.debug(f"  After code removal: '{cleaned_name}'")
        
        # If we have the colour record, remove its exact name
        if colour_record and colour_record.name:
            # Remove the exact colour name (case-insensitive)
            colour_name_pattern = re.escape(colour_record.name)
            before_removal = cleaned_name
            cleaned_name = re.sub(rf'\s*{colour_name_pattern}\s*', ' ', cleaned_name, flags=re.IGNORECASE)
            
            if before_removal != cleaned_name:
                _logger.debug(f"  Removed colour name '{colour_record.name}': '{before_removal}' -> '{cleaned_name}'")
            else:
                _logger.debug(f"  Colour name '{colour_record.name}' not found in name")
        
        # Clean up extra spaces
        cleaned_name = ' '.join(cleaned_name.split())
        _logger.debug(f"  Final cleaned name: '{cleaned_name}'")
        
        return cleaned_name

    def _build_product_name(self, base_name, colour_code, colour_name):
        """
        Build product name with colour name and code: BASE NAME COLOUR_NAME [CODE].
        Used for both normal products and tinted products.
        """
        _logger.debug(f"🔄 _build_product_name() called")
        _logger.debug(f"  Base name: '{base_name}'")
        _logger.debug(f"  Colour code: '{colour_code}'")
        _logger.debug(f"  Colour name: '{colour_name}'")
        
        if not base_name or not colour_code or not colour_name:
            _logger.warning("❌ Invalid input for _build_product_name - missing required parameters")
            _logger.warning(f"  base_name: '{base_name}', colour_code: '{colour_code}', colour_name: '{colour_name}'")
            return base_name or ""
        
        clean_name = base_name.strip()
        parts = clean_name.split()
        suffixes = ['N/A', 'NA', 'TBD', 'TBC']
        
        _logger.debug(f"  Name parts: {parts}")
        _logger.debug(f"  Checking for suffixes: {suffixes}")
        
        # Check if last word is a suffix
        if parts and any(parts[-1].upper() == s for s in suffixes):
            suffix = parts[-1]
            base_without_suffix = ' '.join(parts[:-1]) if parts[:-1] else ""
            _logger.debug(f"  Found suffix: '{suffix}'")
            _logger.debug(f"  Base without suffix: '{base_without_suffix}'")
            
            if base_without_suffix:
                # Format: BASE NAME COLOUR_NAME [CODE] SUFFIX
                result = f"{base_without_suffix} {colour_name} [{colour_code}] {suffix}"
                _logger.debug(f"  Format: BASE + COLOUR_NAME + [CODE] + SUFFIX")
                _logger.debug(f"  Result: '{result}'")
                return result
            else:
                result = f"{colour_name} [{colour_code}] {suffix}"
                _logger.debug(f"  Format: COLOUR_NAME + [CODE] + SUFFIX")
                _logger.debug(f"  Result: '{result}'")
                return result
        else:
            # Format: BASE NAME COLOUR_NAME [CODE]
            result = f"{clean_name} {colour_name} [{colour_code}]"
            _logger.debug(f"  Format: BASE + COLOUR_NAME + [CODE]")
            _logger.debug(f"  Result: '{result}'")
            return result

    # REMOVED @api.onchange to prevent duplication during form input
    # Concatenation will only happen on save (create/write)
    # This prevents double-processing when users type in the form