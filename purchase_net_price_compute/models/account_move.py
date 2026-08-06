# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    vendor_reference_type_id = fields.Many2one(
        'purchase.vendor.reference.type',
        string='Vendor Reference Type',
        tracking=True,
        index=True,
        copy=False,
        domain=[('active', '=', True)],
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

    @api.depends('ref')
    def _compute_vendor_reference_normalized(self):
        for move in self:
            move.vendor_reference_normalized = (move.ref or '').strip().casefold() or False

    def _is_vendor_reference_document(self):
        self.ensure_one()
        return self.move_type in ('in_invoice', 'in_refund', 'in_receipt')

    def _get_vendor_reference_normalized(self):
        self.ensure_one()
        return (self.ref or '').strip().casefold()

    def _is_vendor_reference_required(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            'purchase_net_price_compute.vendor_reference_required_invoice',
            default='True',
        )
        return str(value).lower() not in ('false', '0', 'no', 'off')

    @api.depends('move_type')
    def _compute_vendor_reference_required(self):
        required = self._is_vendor_reference_required()
        for move in self:
            move.vendor_reference_required = move._is_vendor_reference_document() and required

    @api.constrains('ref', 'vendor_reference_type_id', 'company_id', 'move_type')
    def _check_vendor_reference_required_unique(self):
        for move in self:
            if not move._is_vendor_reference_document():
                continue
            normalized_reference = move._get_vendor_reference_normalized()
            has_partial_reference = bool(move.vendor_reference_type_id) != bool(normalized_reference)
            if has_partial_reference:
                raise ValidationError(_('Vendor Reference Type and Vendor Reference must be entered together.'))
            if not normalized_reference:
                continue
            duplicate = self.search([
                ('id', '!=', move.id),
                ('move_type', '=', move.move_type),
                ('company_id', '=', move.company_id.id),
                ('vendor_reference_type_id', '=', move.vendor_reference_type_id.id),
                ('vendor_reference_normalized', '=', normalized_reference),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Vendor Reference "%(reference)s" already exists for type "%(type)s".',
                    reference=move.ref,
                    type=move.vendor_reference_type_id.display_name,
                ))

    def _validate_vendor_reference_required(self):
        if not self._is_vendor_reference_required():
            self._check_vendor_reference_required_unique()
            return
        for move in self.filtered(lambda item: item._is_vendor_reference_document()):
            if not move.vendor_reference_type_id or not move._get_vendor_reference_normalized():
                raise ValidationError(_('Vendor Reference Type and Vendor Reference are mandatory on vendor bills.'))
        self._check_vendor_reference_required_unique()

    def action_post(self):
        self._validate_vendor_reference_required()
        return super().action_post()
