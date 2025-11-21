# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ColorantMappingWizard(models.TransientModel):
    _name = 'colorant.mapping.wizard'
    _description = 'Map Existing Products as Colorants'

    mapping_line_ids = fields.One2many(
        'colorant.mapping.line',
        'wizard_id',
        string='Colorant Mappings'
    )

    @api.model
    def default_get(self, fields_list):
        """Create 16 lines (C1-C16) when wizard opens"""
        res = super().default_get(fields_list)

        if 'mapping_line_ids' not in res or not res.get('mapping_line_ids'):
            lines = []
            for i in range(1, 17):
                code = f'C{i}'

                # Check if already mapped
                existing = self.env['product.template'].search([
                    ('is_colorant', '=', True),
                    ('colorant_code', '=', code)
                ], limit=1)

                lines.append((0, 0, {
                    'colorant_code': code,
                    'product_id': existing.product_variant_id.id if existing else False,
                }))

            res['mapping_line_ids'] = lines

        return res

    def action_map_colorants(self):
        """Map selected products to colorant codes — FIXED FOR ODOO 17/18"""
        self.ensure_one()

        # CRITICAL FIX: In Odoo 17/18, One2many lines are NOT saved before button call
        # We directly query the transient lines that have a product selected
        self.env.cr.execute("""
            SELECT id, colorant_code, product_id
            FROM colorant_mapping_line
            WHERE wizard_id = %s
              AND product_id IS NOT NULL
        """, (self.id,))
        raw_lines = self.env.cr.fetchall()

        if not raw_lines:
            raise ValidationError(_(
                'Warning No Products Selected\n\n'
                'Please select at least one product to map.\n\n'
                'Instructions:\n'
                '1. Select a product for each colorant code\n'
                '2. Click "Save & Map Colorants" again'
            ))

        mapped_count = 0
        skipped_count = 0
        litre_uom = self.env.ref('uom.product_uom_litre', raise_if_not_found=False)

        for line_id, colorant_code, product_id in raw_lines:
            product = self.env['product.product'].browse(product_id)
            template = product.product_tmpl_id

            # Prevent re-mapping to different code
            if template.is_colorant and template.colorant_code and template.colorant_code != colorant_code:
                raise ValidationError(_(
                    'Product "%(product)s" already mapped to "%(existing)s".\n'
                    'Cannot map to "%(new)s".',
                    product=template.name,
                    existing=template.colorant_code,
                    new=colorant_code
                ))

            # Skip if already correctly mapped
            if template.is_colorant and template.colorant_code == colorant_code:
                skipped_count += 1
                continue

            # Map the product
            values = {
                'is_colorant': True,
                'colorant_code': colorant_code,
            }
            if litre_uom:
                values.update({
                    'uom_id': litre_uom.id,
                    'uom_po_id': litre_uom.id,
                })

            template.write(values)
            mapped_count += 1

        # Success message
        message = f'Success!\n\n'
        if mapped_count > 0:
            message += f'• {mapped_count} colorant(s) mapped\n'
        if skipped_count > 0:
            message += f'• {skipped_count} already mapped\n'

        total = self.env['product.template'].search_count([('is_colorant', '=', True)])
        message += f'\nTotal colorants: {total}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success!'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }


class ColorantMappingLine(models.TransientModel):
    _name = 'colorant.mapping.line'
    _description = 'Colorant Mapping Line'
    _order = 'colorant_code'
    _sql_constraints = []  # Remove any SQL constraints

    wizard_id = fields.Many2one(
        'colorant.mapping.wizard',
        required=True,
        ondelete='cascade'
    )

    colorant_code = fields.Char(
        string='Code',
        readonly=True,
        help='Colorant code (C1-C16)'
    )

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        help='Select your colorant product'
    )

    product_name = fields.Char(
        string='Name',
        related='product_id.name',
        readonly=True
    )

    current_uom = fields.Char(
        string='UoM',
        compute='_compute_info',
        store=False
    )

    current_stock = fields.Float(
        string='Stock',
        compute='_compute_info',
        digits=(10, 2),
        store=False
    )

    already_mapped = fields.Boolean(
        string='Mapped',
        compute='_compute_info',
        store=False
    )

    @api.depends('product_id')
    def _compute_info(self):
        """Compute product info"""
        for line in self:
            if line.product_id:
                line.current_uom = line.product_id.uom_id.name
                line.current_stock = line.product_id.qty_available
                line.already_mapped = line.product_id.product_tmpl_id.is_colorant
            else:
                line.current_uom = ''
                line.current_stock = 0.0
                line.already_mapped = False