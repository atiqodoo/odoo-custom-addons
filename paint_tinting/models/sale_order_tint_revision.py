# -*- coding: utf-8 -*-
from odoo import fields, models


class PaintTintingSaleLineRevision(models.Model):
    """Persistent audit trail for quotation tint edits made from sale lines."""

    _name = 'paint.tinting.sale.line.revision'
    _description = 'Sale Order Line Tint Revision'
    _order = 'edited_at desc, id desc'

    name = fields.Char(string='Revision', required=True, readonly=True, copy=False)
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        readonly=True,
        ondelete='cascade',
        index=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        readonly=True,
        ondelete='cascade',
        index=True,
    )
    revision_no = fields.Integer(string='Revision No.', required=True, readonly=True)
    edited_by_id = fields.Many2one(
        'res.users',
        string='Edited By',
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    edited_at = fields.Datetime(
        string='Edited At',
        required=True,
        readonly=True,
        default=fields.Datetime.now,
    )
    change_reason = fields.Text(string='Change Reason', readonly=True)

    before_formula_json = fields.Text(string='Before Formula JSON', readonly=True)
    after_formula_json = fields.Text(string='After Formula JSON', readonly=True)
    metadata_json = fields.Text(string='Metadata / Diff JSON', readonly=True)

    before_colour_code_id = fields.Many2one('colour.code', string='Before Colour Code', readonly=True)
    after_colour_code_id = fields.Many2one('colour.code', string='After Colour Code', readonly=True)
    before_fandeck_id = fields.Many2one('colour.fandeck', string='Before Fandeck', readonly=True)
    after_fandeck_id = fields.Many2one('colour.fandeck', string='After Fandeck', readonly=True)
    before_base_category_id = fields.Many2one('product.category', string='Before Base Category', readonly=True)
    after_base_category_id = fields.Many2one('product.category', string='After Base Category', readonly=True)
    before_base_product_id = fields.Many2one('product.product', string='Before Base Product', readonly=True)
    after_base_product_id = fields.Many2one('product.product', string='After Base Product', readonly=True)
    before_base_product_uom_id = fields.Many2one('uom.uom', string='Before Base UOM', readonly=True)
    after_base_product_uom_id = fields.Many2one('uom.uom', string='After Base UOM', readonly=True)

    before_base_cost_incl_vat = fields.Float(string='Before Base Cost Incl. VAT', digits='Product Price', readonly=True)
    after_base_cost_incl_vat = fields.Float(string='After Base Cost Incl. VAT', digits='Product Price', readonly=True)
    before_colorant_cost_incl_vat = fields.Float(string='Before Colorant Cost Incl. VAT', digits='Product Price', readonly=True)
    after_colorant_cost_incl_vat = fields.Float(string='After Colorant Cost Incl. VAT', digits='Product Price', readonly=True)
    before_total_cost_incl_vat = fields.Float(string='Before Total Cost Incl. VAT', digits='Product Price', readonly=True)
    after_total_cost_incl_vat = fields.Float(string='After Total Cost Incl. VAT', digits='Product Price', readonly=True)
    before_price_unit = fields.Float(string='Before Selling Price', digits='Product Price', readonly=True)
    after_price_unit = fields.Float(string='After Selling Price', digits='Product Price', readonly=True)
