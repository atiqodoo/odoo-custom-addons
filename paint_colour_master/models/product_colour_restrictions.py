from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProductTemplateColourRestrictions(models.Model):
    _inherit = 'product.template'

    @api.constrains('colour_code_id', 'attribute_line_ids')
    def _check_no_variants_with_colour(self):
        """Prevent adding attributes/variants when colour code is assigned."""
        for record in self:
            if record.colour_code_id and record.attribute_line_ids:
                raise ValidationError(
                    'Cannot assign Product Attributes or Variants to products with a Colour Code.\n\n'
                    'Products with colour codes must be single products without variants.\n'
                    'Please remove the Colour Code or the Attributes/Variants.'
                )

    @api.constrains('colour_code_id', 'product_variant_ids')
    def _check_single_variant_only(self):
        """Ensure only one variant exists when colour code is assigned."""
        for record in self:
            if record.colour_code_id and len(record.product_variant_ids) > 1:
                raise ValidationError(
                    'Products with Colour Codes can only have ONE product variant.\n\n'
                    'This product has multiple variants. Please remove variants or the Colour Code.'
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to block attributes when colour code is present."""
        for vals in vals_list:
            if vals.get('colour_code_id') and vals.get('attribute_line_ids'):
                raise ValidationError(
                    'Cannot create a product with both Colour Code and Attributes/Variants.\n\n'
                    'Products with colour codes must be single products without variants.'
                )
        return super().create(vals_list)

    def write(self, vals):
        """Override write to prevent adding attributes to colour products."""
        # Check if trying to add colour code to a product with variants
        if vals.get('colour_code_id'):
            for record in self:
                # Calculate the FINAL state of attribute_line_ids after this write
                final_attributes = record.attribute_line_ids
                
                # If attribute_line_ids is being modified in this write, calculate final state
                if 'attribute_line_ids' in vals:
                    # Process the ORM commands to see final state
                    attr_commands = vals.get('attribute_line_ids', [])
                    
                    # Check if all attributes are being deleted
                    # Commands: (5,) = delete all, (2, id) = delete one, (3, id) = unlink
                    is_deleting_all = False
                    for cmd in attr_commands:
                        if isinstance(cmd, (list, tuple)):
                            if cmd[0] == 5:  # (5, 0, 0) = delete all
                                is_deleting_all = True
                                final_attributes = self.env['product.template.attribute.line']
                                break
                    
                    # If not deleting all, check if there will be any attributes left
                    if not is_deleting_all and final_attributes:
                        # User is trying to add colour but not removing all attributes
                        raise ValidationError(
                            'Cannot assign a Colour Code to products with Attributes/Variants.\n\n'
                            'This product has Attributes and Variants configured. '
                            'Please remove all Attributes and Variants first from the "Attributes & Variants" tab, '
                            'then assign the Colour Code.'
                        )
                else:
                    # attribute_line_ids not in vals, check current state
                    if record.attribute_line_ids:
                        raise ValidationError(
                            'Cannot assign a Colour Code to products with Attributes/Variants.\n\n'
                            'This product has Attributes and Variants configured. '
                            'Please remove all Attributes and Variants first from the "Attributes & Variants" tab, '
                            'then assign the Colour Code.'
                        )
                
                # Also check variants
                if not vals.get('attribute_line_ids') and record.product_variant_ids and len(record.product_variant_ids) > 1:
                    raise ValidationError(
                        'Cannot assign a Colour Code to products with multiple variants.\n\n'
                        f'This product has {len(record.product_variant_ids)} variants. '
                        'Please remove all variants first, then assign the Colour Code.'
                    )
        
        # Check if trying to add attributes to a product with colour code
        if vals.get('attribute_line_ids'):
            for record in self:
                if record.colour_code_id or vals.get('colour_code_id'):
                    # Check if actually adding attributes (not deleting)
                    attr_commands = vals.get('attribute_line_ids', [])
                    is_adding = False
                    
                    for cmd in attr_commands:
                        if isinstance(cmd, (list, tuple)):
                            # Commands: 0=create, 1=update, 4=link (adding)
                            # Commands: 2=delete, 3=unlink, 5=delete all (removing)
                            if cmd[0] in (0, 1, 4):
                                is_adding = True
                                break
                    
                    if is_adding:
                        raise ValidationError(
                            'Cannot add Attributes/Variants to products with a Colour Code.\n\n'
                            'Products with colour codes must be single products without variants.\n'
                            'Please remove the Colour Code first.'
                        )
        
        return super().write(vals)

    def copy(self, default=None):
        """Override copy (duplicate) to remove attributes/variants when colour code exists."""
        default = dict(default or {})
        
        # If the product being duplicated has a colour code, remove attributes/variants
        if self.colour_code_id:
            _logger.info(f"Duplicating product '{self.name}' with colour code. Removing attributes/variants from duplicate.")
            
            # Clear attributes and variants from the duplicate
            default['attribute_line_ids'] = [(5, 0, 0)]  # Remove all attribute lines
            
            # Also clear the colour code fields to allow user to select new colour
            default['colour_code_id'] = False
            default['fandeck_id'] = False
            default['colour_name'] = False
            default['base_product_name'] = self.base_product_name or self._strip_colour_code_from_name(self.name)
            
            _logger.info(f"Duplicate will be created without attributes/variants. User must select new colour.")
        
        return super().copy(default)

    def _strip_colour_code_from_name(self, name):
        """Helper to strip [CODE] from product name during duplication."""
        import re
        if not name:
            return ""
        cleaned = re.sub(r'\s*\[[\w\-]+\]\s*', ' ', name)
        # Also try to remove colour name (last 1-2 caps words before potential suffix)
        words = cleaned.split()
        if len(words) > 2:
            # Check if last or second-to-last words are all caps (likely colour name)
            if words[-1].isupper():
                words = words[:-1]
            elif len(words) > 1 and words[-2].isupper():
                # Keep suffix if last word is N/A, etc.
                if words[-1].upper() in ['N/A', 'NA', 'TBD', 'TBC']:
                    words = words[:-2] + [words[-1]]
                else:
                    words = words[:-1]
        return ' '.join(words).strip()


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.constrains('product_tmpl_id')
    def _check_colour_product_single_variant(self):
        """Ensure colour products remain single variants."""
        for record in self:
            if record.product_tmpl_id.colour_code_id:
                variant_count = len(record.product_tmpl_id.product_variant_ids)
                if variant_count > 1:
                    raise ValidationError(
                        f'Product "{record.product_tmpl_id.name}" has a Colour Code and cannot have multiple variants.\n\n'
                        f'Currently has {variant_count} variants. Only 1 variant is allowed for colour products.'
                    )