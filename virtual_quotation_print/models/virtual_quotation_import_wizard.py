# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VirtualQuotationImportSaleWizard(models.TransientModel):
    _name = 'virtual.quotation.import.sale.wizard'
    _description = 'Load Real Quotation Lines into Virtual Quote'
    _inherit = 'virtual.quotation.log.mixin'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Source Quotation',
        required=True,
        domain=[('state', 'in', ['draft', 'sent', 'sale', 'done'])],
    )
    target_quotation_id = fields.Many2one(
        'virtual.quotation',
        string='Draft Virtual Quote',
        domain=[('state', '=', 'draft')],
        help='Leave empty to create a new virtual quote from the selected real quotation.',
    )
    replace_lines = fields.Boolean(
        string='Replace Existing Lines',
        help='When enabled, existing draft virtual quote lines are removed before loading the real quotation lines.',
    )
    result_mode = fields.Selection(
        [('open', 'Open Virtual Quote'), ('stay', 'Stay Here')],
        default='open',
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')
        if active_model == 'virtual.quotation' and active_id:
            quotation = self.env['virtual.quotation'].browse(active_id).exists()
            if quotation:
                values.setdefault('target_quotation_id', quotation.id)
                if quotation.linked_sale_order_id:
                    values.setdefault('sale_order_id', quotation.linked_sale_order_id.id)
        elif active_model == 'sale.order' and active_id:
            order = self.env['sale.order'].browse(active_id).exists()
            if order:
                values.setdefault('sale_order_id', order.id)
        return values

    def action_load_lines(self):
        self.ensure_one()
        self._vq_log(
            'IMPORT WIZARD LOAD START',
            sale_order_id=self.sale_order_id.id,
            target_quotation_id=self.target_quotation_id.id,
            replace_lines=self.replace_lines,
        )
        if self.target_quotation_id and self.target_quotation_id.state != 'draft':
            raise UserError(_('Only draft virtual quotations can receive imported lines.'))
        quotation = self.env['virtual.quotation.service'].load_sale_order_into_virtual_quote(
            self.sale_order_id,
            quotation=self.target_quotation_id,
            replace_lines=self.replace_lines,
        )
        if self.result_mode == 'stay':
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': quotation.display_name,
            'res_model': 'virtual.quotation',
            'res_id': quotation.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }
