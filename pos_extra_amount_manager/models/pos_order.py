# -*- coding: utf-8 -*-
"""
POS Order Extension
Aggregates extra amounts and manages distribution workflow.
"""
from odoo import models, fields, api
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'
    
    extra_state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('distributed', 'Distributed'),
    ], string='Extra State', default='draft', tracking=True)
    
    # === TOTALS ===
    total_extra_amount = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    total_extra_cogs = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    total_distributed_amount = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    remaining_extra_amount = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    
    extra_distribution_ids = fields.One2many('pos.extra.distribution', 'pos_order_id', string='Distributions')
    distribution_count = fields.Integer(compute='_compute_distribution_count')
    
    @api.depends('lines.total_extra_amount', 'lines.product_cost', 'extra_distribution_ids.distribution_amount')
    def _compute_totals(self):
        for order in self:
            order.total_extra_amount = sum(order.lines.mapped('total_extra_amount'))
            order.total_extra_cogs = sum(order.lines.mapped('product_cost'))
            order.total_distributed_amount = sum(
                order.extra_distribution_ids.filtered(lambda d: d.state == 'posted').mapped('distribution_amount')
            )
            order.remaining_extra_amount = order.total_extra_amount - order.total_distributed_amount
    
    @api.depends('extra_distribution_ids')
    def _compute_distribution_count(self):
        for order in self:
            order.distribution_count = len(order.extra_distribution_ids)
    
    # === ACTIONS ===
    def action_calculate_extra_amount(self):
        self.ensure_one()
        self.lines._compute_extra_amount()
        self.extra_state = 'calculated'
        return self._notify_success('Extra amounts calculated.')
    
    def action_open_distribution_wizard(self):
        self.ensure_one()
        if self.extra_state == 'draft':
            raise UserError('Calculate extra amounts first.')
        if self.remaining_extra_amount <= 0:
            raise UserError('No remaining amount to distribute.')
        return {
            'name': 'Distribute Extra',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.extra.distribution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context | {
                'default_pos_order_id': self.id,
                'default_total_extra_amount': self.total_extra_amount,
                'default_remaining_extra_amount': self.remaining_extra_amount,
                'default_total_extra_cogs': self.total_extra_cogs,
            }
        }
    
    def action_view_distributions(self):
        return {
            'name': 'Distributions',
            'type': 'ir.actions.act_window',
            'res_model': 'pos.extra.distribution',
            'view_mode': 'list,form',
            'domain': [('pos_order_id', '=', self.id)],
        }
    
    def action_reset_extra_state(self):
        self.ensure_one()
        if self.extra_distribution_ids:
            raise UserError('Cannot reset with existing distributions.')
        self.extra_state = 'draft'
        return self._notify_success('State reset to Draft.')
    
    def _notify_success(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Success', 'message': message, 'type': 'success', 'sticky': False}
        }