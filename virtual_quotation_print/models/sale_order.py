# -*- coding: utf-8 -*-

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    virtual_quotation_ids = fields.One2many(
        'virtual.quotation',
        'linked_sale_order_id',
        string='Virtual Print Quotes',
    )
    virtual_quotation_count = fields.Integer(compute='_compute_virtual_quotation_count')

    def _compute_virtual_quotation_count(self):
        for order in self:
            order.virtual_quotation_count = len(order.virtual_quotation_ids)

    def action_view_virtual_quotations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Virtual Print Quotes',
            'res_model': 'virtual.quotation',
            'view_mode': 'list,form',
            'domain': [('linked_sale_order_id', '=', self.id)],
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_linked_sale_order_id': self.id,
                'default_pricelist_id': self.pricelist_id.id,
                'default_payment_term_id': self.payment_term_id.id,
                'default_validity_date': self.validity_date,
            },
        }

    def action_create_virtual_quotation_from_sale(self):
        self.ensure_one()
        wizard = self.env['virtual.quotation.import.sale.wizard'].create({
            'sale_order_id': self.id,
            'replace_lines': False,
        })
        return wizard.action_load_lines()
