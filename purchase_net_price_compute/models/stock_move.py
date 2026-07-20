# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = 'stock.move'

    receipt_volume_reporting_grade_id = fields.Many2one(
        'product.tag',
        string='Grade',
        compute='_compute_receipt_grade_values',
        store=True,
        readonly=True,
        index=True,
    )
    receipt_volume_reference_uom_id = fields.Many2one(
        'uom.uom',
        string='Grade Volume UoM',
        compute='_compute_receipt_grade_values',
        store=True,
        readonly=True,
    )
    receipt_grade_volume = fields.Float(
        string='Grade Volume',
        compute='_compute_receipt_grade_values',
        store=True,
        readonly=True,
        digits='Product Unit of Measure',
    )
    receipt_grade_volume_label = fields.Char(
        string='Grade Volume',
        compute='_compute_receipt_grade_values',
        store=True,
        readonly=True,
    )
    receipt_grade_amount_vat_incl = fields.Monetary(
        string='Grade Value (VAT Incl.)',
        compute='_compute_receipt_grade_values',
        store=True,
        readonly=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='purchase_line_id.currency_id',
        readonly=True,
        store=True,
    )

    def _receipt_grade_base_qty(self):
        self.ensure_one()
        return self.quantity if self.state == 'done' else self.product_uom_qty

    @api.depends(
        'purchase_line_id',
        'purchase_line_id.volume_reporting_grade_id',
        'purchase_line_id.volume_reference_uom_id',
        'purchase_line_id.price_total',
        'purchase_line_id.product_qty',
        'purchase_line_id.product_uom',
        'product_uom',
        'product_uom_qty',
        'quantity',
        'state',
    )
    def _compute_receipt_grade_values(self):
        for move in self:
            purchase_line = move.purchase_line_id
            if not purchase_line or not move.product_uom:
                move.receipt_volume_reporting_grade_id = False
                move.receipt_volume_reference_uom_id = False
                move.receipt_grade_volume = 0.0
                move.receipt_grade_volume_label = False
                move.receipt_grade_amount_vat_incl = 0.0
                continue

            reference_uom = purchase_line.volume_reference_uom_id
            if not reference_uom:
                try:
                    reference_uom = self.env['product.movement.volume.builder']._get_category_reference_uom(
                        move.product_uom
                    )
                except Exception as error:
                    _logger.warning(
                        "RECEIPT_GRADE_VOLUME_UOM_FAILED move_id=%s product_id=%s uom_id=%s error=%s",
                        move.id,
                        move.product_id.id,
                        move.product_uom.id,
                        error,
                    )
                    reference_uom = self.env['uom.uom']

            receipt_qty = move._receipt_grade_base_qty()
            try:
                grade_volume = move.product_uom._compute_quantity(
                    receipt_qty or 0.0,
                    reference_uom,
                    round=False,
                ) if reference_uom else 0.0
            except Exception as error:
                _logger.warning(
                    "RECEIPT_GRADE_VOLUME_FAILED move_id=%s product_id=%s qty=%s error=%s",
                    move.id,
                    move.product_id.id,
                    receipt_qty,
                    error,
                )
                grade_volume = 0.0

            receipt_qty_in_po_uom = 0.0
            if purchase_line.product_uom and purchase_line.product_qty:
                receipt_qty_in_po_uom = move.product_uom._compute_quantity(
                    receipt_qty or 0.0,
                    purchase_line.product_uom,
                    round=False,
                )
            receipt_ratio = (
                receipt_qty_in_po_uom / purchase_line.product_qty
                if purchase_line.product_qty
                else 0.0
            )

            move.receipt_volume_reporting_grade_id = purchase_line.volume_reporting_grade_id
            move.receipt_volume_reference_uom_id = reference_uom
            move.receipt_grade_volume = grade_volume
            move.receipt_grade_volume_label = (
                f"{purchase_line.order_id._lpo_report_format_float(grade_volume, 2)} {reference_uom.name}"
                if reference_uom
                else purchase_line.order_id._lpo_report_format_float(grade_volume, 2)
            )
            move.receipt_grade_amount_vat_incl = (purchase_line.price_total or 0.0) * receipt_ratio
