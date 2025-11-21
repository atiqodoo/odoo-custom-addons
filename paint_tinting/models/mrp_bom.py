# -*- coding: utf-8 -*-

from odoo import models, fields, api


class MrpBom(models.Model):
    """Extension of mrp.bom to add tinting-specific fields and costing"""
    _inherit = 'mrp.bom'

    # Tinting identification
    is_tinting_bom = fields.Boolean(
        string='Is Tinting BOM',
        default=False,
        help='Indicates if this BOM was created through the tinting wizard'
    )
    
    # Costing summary fields
    total_cost_excl_vat = fields.Float(
        string='Total Cost (Excl. VAT)',
        compute='_compute_total_costs',
        store=True,
        digits='Product Price',
        help='Sum of all BOM line costs excluding VAT'
    )
    
    total_cost_incl_vat = fields.Float(
        string='Total Cost (Incl. VAT)',
        compute='_compute_total_costs',
        store=True,
        digits='Product Price',
        help='Sum of all BOM line costs including VAT'
    )
    
    # Tinting metadata
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        help='Fandeck used for this tinted product'
    )
    
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        help='Colour code used for this tinted product'
    )
    
    base_variant_id = fields.Many2one(
        'product.product',
        string='Base Variant Used',
        help='The specific base paint variant used in this BOM'
    )
    
    pack_size_uom_id = fields.Many2one(
        'uom.uom',
        string='Pack Size',
        help='Volume UoM used (1L, 4L, 20L)'
    )
    
    tinting_notes = fields.Text(
        string='Tinting Notes',
        help='Additional notes about this tinting recipe'
    )
    
    @api.depends('bom_line_ids.cost_excl_vat', 'bom_line_ids.cost_incl_vat')
    def _compute_total_costs(self):
        """Calculate total costs from BOM lines"""
        for bom in self:
            bom.total_cost_excl_vat = sum(line.cost_excl_vat for line in bom.bom_line_ids)
            bom.total_cost_incl_vat = sum(line.cost_incl_vat for line in bom.bom_line_ids)
    
    def action_view_cost_breakdown(self):
        """Action to view detailed cost breakdown of BOM"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'BOM Cost Breakdown',
            'res_model': 'mrp.bom.line',
            'view_mode': 'list,form',
            'domain': [('bom_id', '=', self.id)],
            'context': {'default_bom_id': self.id},
        }
