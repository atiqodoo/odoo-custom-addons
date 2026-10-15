# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    vendor_reference_type_id = fields.Many2one(
        'purchase.vendor.reference.type',
        string='Vendor Reference Type',
        tracking=True,
        index=True,
        copy=False,
        domain=[('active', '=', True)],
    )
    vendor_reference = fields.Char(
        string='Vendor Reference',
        tracking=True,
        index=True,
        copy=False,
    )
    vendor_reference_required = fields.Boolean(
        compute='_compute_vendor_reference_required',
    )
    vendor_reference_normalized = fields.Char(
        string='Vendor Reference Search Key',
        compute='_compute_vendor_reference_normalized',
        store=True,
        index=True,
        copy=False,
    )

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

    @api.depends('vendor_reference')
    def _compute_vendor_reference_normalized(self):
        for picking in self:
            picking.vendor_reference_normalized = (picking.vendor_reference or '').strip().casefold() or False

    def _get_vendor_reference_normalized(self):
        self.ensure_one()
        return (self.vendor_reference or '').strip().casefold()

    def _is_vendor_reference_required(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_net_price_compute.vendor_reference_required_receipt',
            default='True',
        )
        return str(value).lower() not in ('false', '0', 'no', 'off')

    @api.depends('picking_type_code')
    def _compute_vendor_reference_required(self):
        required = self._is_vendor_reference_required()
        for picking in self:
            picking.vendor_reference_required = picking.picking_type_code == 'incoming' and required

    @api.constrains('vendor_reference', 'vendor_reference_type_id', 'company_id', 'picking_type_code')
    def _check_vendor_reference_unique(self):
        for picking in self:
            normalized_reference = picking._get_vendor_reference_normalized()
            if picking.picking_type_code != 'incoming' or not normalized_reference:
                if picking.picking_type_code == 'incoming' and bool(picking.vendor_reference_type_id) != bool(normalized_reference):
                    raise ValidationError(_('Vendor Reference Type and Vendor Reference must be entered together.'))
                continue
            if not picking.vendor_reference_type_id:
                raise ValidationError(_('Vendor Reference Type and Vendor Reference must be entered together.'))
            duplicate = self.search([
                ('id', '!=', picking.id),
                ('picking_type_code', '=', 'incoming'),
                ('company_id', '=', picking.company_id.id),
                ('vendor_reference_type_id', '=', picking.vendor_reference_type_id.id),
                ('vendor_reference_normalized', '=', normalized_reference),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Vendor Reference "%(reference)s" already exists for type "%(type)s".',
                    reference=picking.vendor_reference,
                    type=picking.vendor_reference_type_id.display_name,
                ))

    def button_validate(self):
        if not self._is_vendor_reference_required():
            self._check_vendor_reference_unique()
            return super().button_validate()
        for picking in self.filtered(lambda item: item.picking_type_code == 'incoming'):
            if not picking.vendor_reference_type_id or not picking._get_vendor_reference_normalized():
                raise ValidationError(_('Vendor Reference Type and Vendor Reference are mandatory on receipts.'))
        return super().button_validate()

    def action_open_vendor_document_tally(self):
        self.ensure_one()
        session = self.env['vendor.document.tally.session']._get_or_create_for_record(self)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Vendor Document Tally'),
            'res_model': 'vendor.document.tally.session',
            'view_mode': 'form',
            'res_id': session.id,
            'target': 'current',
        }

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
