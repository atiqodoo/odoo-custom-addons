# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    receipt_grade_volume_summary = fields.Text(
        string='Receipt Grade Volume Summary',
        compute='_compute_receipt_grade_volume_summary',
        store=True,
        readonly=True,
        tracking=True,
    )
    receipt_grade_volume_summary_json = fields.Json(
        string='Receipt Grade Volume Summary Snapshot',
        compute='_compute_receipt_grade_volume_summary',
        store=True,
        readonly=True,
        help='Stored receipt grade-wise volume and VAT-inclusive value snapshot for posted bill comparison.',
    )

    @api.depends(
        'move_ids.receipt_volume_reporting_grade_id',
        'move_ids.receipt_volume_reference_uom_id',
        'move_ids.receipt_grade_volume',
        'move_ids.receipt_grade_amount_vat_incl',
        'move_ids.state',
        'move_ids.scrapped',
    )
    def _compute_receipt_grade_volume_summary(self):
        for picking in self:
            totals = {}
            for move in picking.move_ids.filtered(
                lambda item: (
                    not item.scrapped
                    and item.product_id
                    and (item.receipt_grade_volume or item.receipt_grade_amount_vat_incl)
                )
            ):
                grade_id = move.receipt_volume_reporting_grade_id.id or False
                grade_name = (
                    move.receipt_volume_reporting_grade_id.display_name
                    if move.receipt_volume_reporting_grade_id
                    else _('Unmapped Grade')
                )
                uom_id = move.receipt_volume_reference_uom_id.id or False
                uom_name = move.receipt_volume_reference_uom_id.name or ''
                currency = move.currency_id or picking.company_id.currency_id
                key = (grade_id, grade_name, uom_id, uom_name, currency.id)
                if key not in totals:
                    totals[key] = {
                        'grade_id': grade_id,
                        'grade_name': grade_name,
                        'uom_id': uom_id,
                        'uom_name': uom_name,
                        'volume': 0.0,
                        'amount_vat_incl': 0.0,
                        'currency_id': currency.id,
                        'currency_name': currency.name,
                    }
                totals[key]['volume'] += move.receipt_grade_volume or 0.0
                totals[key]['amount_vat_incl'] += move.receipt_grade_amount_vat_incl or 0.0

            lines = []
            snapshot = []
            volume_totals = {}
            amount_total = 0.0
            for key, values in sorted(totals.items(), key=lambda item: (item[0][1], item[0][3])):
                currency = self.env['res.currency'].browse(values['currency_id'])
                amount = currency.round(values['amount_vat_incl']) if currency else values['amount_vat_incl']
                amount_text = f"{values['currency_name']} {amount:,.2f}"
                volume_text = (
                    picking.purchase_id._lpo_report_format_float(values['volume'], 2)
                    if picking.purchase_id
                    else f"{values['volume']:,.2f}".rstrip('0').rstrip('.')
                )
                volume_suffix = f" {values['uom_name']}" if values['uom_name'] else ''
                lines.append(
                    _(
                        "%(grade)s Grade Received Volume: %(volume)s%(uom)s / %(amount)s VAT Incl.",
                        grade=values['grade_name'],
                        volume=volume_text,
                        uom=volume_suffix,
                        amount=amount_text,
                    )
                )
                snapshot.append(values)
                volume_totals[values['uom_name']] = volume_totals.get(values['uom_name'], 0.0) + values['volume']
                amount_total += values['amount_vat_incl']

            if snapshot:
                default_currency = picking.company_id.currency_id
                if len({item['currency_id'] for item in snapshot}) == 1:
                    default_currency = self.env['res.currency'].browse(snapshot[0]['currency_id'])
                volume_parts = []
                for uom_name, volume in sorted(volume_totals.items()):
                    volume_text = (
                        picking.purchase_id._lpo_report_format_float(volume, 2)
                        if picking.purchase_id
                        else f"{volume:,.2f}".rstrip('0').rstrip('.')
                    )
                    volume_parts.append(f"{volume_text} {uom_name}".strip())
                amount_total = default_currency.round(amount_total) if default_currency else amount_total
                lines.append(
                    _(
                        "TOTAL Grade Received: %(volume)s / %(amount)s VAT Incl.",
                        volume=", ".join(volume_parts),
                        amount=f"{default_currency.name} {amount_total:,.2f}" if default_currency else f"{amount_total:,.2f}",
                    )
                )

            picking.receipt_grade_volume_summary = "\n".join(lines)
            picking.receipt_grade_volume_summary_json = snapshot
