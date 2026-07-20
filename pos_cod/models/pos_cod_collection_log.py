# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_COD_LOG = '[COD][CollectionLog]'


class PosCodCollectionLog(models.Model):
    _inherit = 'pos.cod.collection'

    cod_session_user_id = fields.Many2one(
        'res.users',
        string='Session Responsible User',
        related='session_id.user_id',
        readonly=True,
    )
    cod_order_delivery_employee_id = fields.Many2one(
        'hr.employee',
        string='Delivery Employee',
        related='order_id.delivery_employee_id',
        readonly=True,
    )
    cod_return_line_summary = fields.Text(
        string='Returned Lines',
        compute='_compute_cod_return_line_summary',
        readonly=True,
    )

    @api.depends('kind', 'return_line_qtys')
    def _compute_cod_return_line_summary(self):
        product_model = self.env['product.product']
        product_ids = set()
        for collection in self:
            for item in collection.return_line_qtys or []:
                product_id = int(item.get('product_id') or 0)
                if product_id:
                    product_ids.add(product_id)

        products = product_model.browse(product_ids).exists()
        product_names = {product.id: product.display_name for product in products}

        for collection in self:
            if collection.kind != 'return' or not collection.return_line_qtys:
                collection.cod_return_line_summary = False
                continue

            parts = []
            for item in collection.return_line_qtys:
                product_id = int(item.get('product_id') or 0)
                qty = float(item.get('qty') or 0.0)
                if not product_id or qty <= 0:
                    continue
                parts.append('%s: %s' % (product_names.get(product_id, product_id), qty))

            collection.cod_return_line_summary = ', '.join(parts) if parts else False
            _logger.debug(
                '%s return summary: collection=%s order=%s summary=%s',
                _COD_LOG,
                collection.id,
                collection.order_id.name,
                collection.cod_return_line_summary,
            )
