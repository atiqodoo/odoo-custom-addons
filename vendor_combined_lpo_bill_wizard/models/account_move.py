# -*- coding: utf-8 -*-
import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    combined_lpo_bill_source = fields.Boolean(
        string='Combined LPO Bill',
        copy=False,
        readonly=True,
        index=True,
    )
    combined_purchase_ids = fields.Many2many(
        'purchase.order',
        'combined_lpo_bill_purchase_rel',
        'move_id',
        'purchase_id',
        string='Combined Source LPOs',
        copy=False,
        readonly=True,
    )
    combined_lpo_origin_text = fields.Char(
        string='Combined LPO Origins',
        copy=False,
        readonly=True,
    )
    combined_lpo_line_count = fields.Integer(
        string='Combined LPO Line Count',
        copy=False,
        readonly=True,
    )
    combined_lpo_debug_summary = fields.Text(
        string='Combined LPO Debug Summary',
        copy=False,
        readonly=True,
    )

    def _check_vendor_bill_prices(self):
        result = super()._check_vendor_bill_prices()
        for move in self.filtered('combined_lpo_bill_source'):
            _logger.info(
                '[CLPO_PRICE_CHECK] bill_id=%s bill=%s discrepancy_count=%s purchase_ids=%s',
                move.id,
                move.name or 'Draft',
                len(move.discrepancy_ids),
                move.combined_purchase_ids.ids,
            )
        return result


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    combined_lpo_source_purchase_id = fields.Many2one(
        'purchase.order',
        string='Combined Source LPO',
        related='purchase_line_id.order_id',
        store=True,
        readonly=True,
    )
