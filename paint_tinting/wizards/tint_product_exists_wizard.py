# -*- coding: utf-8 -*-
import logging
from odoo import models, fields
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TintProductExistsWizard(models.TransientModel):
    _name = 'tint.product.exists.wizard'
    _description = 'Tinted Product Already Exists'

    product_name = fields.Char(string='Product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Existing Product', readonly=True)
    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order', readonly=True)
    mo_name = fields.Char(string='MO Reference', related='mo_id.name', readonly=True)
    mo_state = fields.Selection(related='mo_id.state', string='MO Status', readonly=True)
    mo_qty = fields.Float(related='mo_id.product_qty', string='Qty', readonly=True)

    # SO that triggered this wizard — used to navigate back after production
    source_sale_order_id = fields.Many2one(
        'sale.order',
        string='Source Sales Order',
        readonly=True,
    )
    source_so_name = fields.Char(
        string='Sales Order',
        related='source_sale_order_id.name',
        readonly=True,
    )
    # SO line that triggered this wizard — used to update the line after MO duplication
    source_sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Source SO Line',
        readonly=True,
    )

    def action_open_mo(self):
        self.ensure_one()
        if not self.mo_id:
            raise UserError("No Manufacturing Order found for this product.")
        ctx = dict(self.env.context)
        if self.source_sale_order_id:
            ctx['source_sale_order_id'] = self.source_sale_order_id.id
            ctx['source_so_name'] = self.source_sale_order_id.name
        if self.source_sale_order_line_id:
            ctx['source_sale_order_line_id'] = self.source_sale_order_line_id.id
        return {
            'type': 'ir.actions.act_window',
            'name': self.mo_id.name,
            'res_model': 'mrp.production',
            'res_id': self.mo_id.id,
            'view_mode': 'form',
            'target': 'current',
            'context': ctx,
        }

    def action_open_all_mos(self):
        self.ensure_one()
        if not self.product_tmpl_id:
            raise UserError("No product reference found.")
        mos = self.env['mrp.production'].search([
            ('product_id.product_tmpl_id', '=', self.product_tmpl_id.id)
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': 'Manufacturing Orders — %s' % self.product_name,
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mos.ids)],
            'target': 'current',
        }

    def action_return_to_so(self):
        self.ensure_one()
        if not self.source_sale_order_id:
            raise UserError("No source sales order linked to this dialog.")
        return {
            'type': 'ir.actions.act_window',
            'name': self.source_sale_order_id.name,
            'res_model': 'sale.order',
            'res_id': self.source_sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
