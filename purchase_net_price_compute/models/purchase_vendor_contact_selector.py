# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    vendor_contact_department_id = fields.Many2one(
        'vendor.department',
        string='Vendor Department',
        tracking=True,
        index=True,
        help='Department used when selecting or quick-creating the vendor contact.',
    )
    vendor_promised_cost_contact_id = fields.Many2one(
        'vendor.department.contact',
        string='Vendor Sales/Customer Service Contact',
        tracking=True,
        index=True,
        help='Vendor department contact who confirmed the promised VAT-inclusive cost.',
    )

    def _purchase_vendor_contact_snapshot(self, department_contact):
        if not department_contact:
            return False
        contact = department_contact.contact_id
        title = department_contact.title or contact.function
        return (
            f'{contact.display_name} - {title}'
            if title
            else contact.display_name
        )

    def _sync_purchase_vendor_contact_values(self, vals):
        contact_model = self.env['vendor.department.contact']
        if 'vendor_promised_cost_contact_id' not in vals:
            return vals

        vals = dict(vals)
        department_contact = contact_model.browse(
            vals.get('vendor_promised_cost_contact_id')
        ).exists()
        vals['vendor_promised_cost_contact'] = self._purchase_vendor_contact_snapshot(
            department_contact
        )
        if department_contact and not vals.get('vendor_contact_department_id'):
            vals['vendor_contact_department_id'] = department_contact.department_id.id
        _logger.debug(
            "RFQ vendor contact sync vals_contact_line_id=%s vals_department_id=%s snapshot=%s",
            vals.get('vendor_promised_cost_contact_id'),
            vals.get('vendor_contact_department_id'),
            vals.get('vendor_promised_cost_contact'),
        )
        return vals

    @api.onchange('partner_id')
    def _onchange_partner_vendor_contact_selector(self):
        for order in self:
            vendor = order.partner_id
            _logger.debug(
                "RFQ vendor changed order_id=%s order=%s vendor_id=%s",
                order.id,
                order.name,
                vendor.id if vendor else False,
            )
            if not vendor:
                order.vendor_contact_department_id = False
                order.vendor_promised_cost_contact_id = False
                order.vendor_promised_cost_contact = False
                continue
            if (
                order.vendor_contact_department_id
                and order.vendor_contact_department_id.vendor_id != vendor
            ):
                _logger.info(
                    "RFQ cleared vendor department after vendor change order_id=%s old_department_id=%s vendor_id=%s",
                    order.id,
                    order.vendor_contact_department_id.id,
                    vendor.id,
                )
                order.vendor_contact_department_id = False
            if (
                order.vendor_promised_cost_contact_id
                and order.vendor_promised_cost_contact_id.vendor_id != vendor
            ):
                _logger.info(
                    "RFQ cleared vendor contact after vendor change order_id=%s old_contact_line_id=%s vendor_id=%s",
                    order.id,
                    order.vendor_promised_cost_contact_id.id,
                    vendor.id,
                )
                order.vendor_promised_cost_contact_id = False
                order.vendor_promised_cost_contact = False

    @api.onchange('vendor_contact_department_id')
    def _onchange_vendor_contact_department_id(self):
        for order in self:
            department = order.vendor_contact_department_id
            _logger.debug(
                "RFQ vendor department changed order_id=%s department_id=%s vendor_id=%s",
                order.id,
                department.id if department else False,
                department.vendor_id.id if department else False,
            )
            if (
                department
                and order.partner_id
                and department.vendor_id != order.partner_id
            ):
                order.vendor_contact_department_id = False
                raise ValidationError(
                    _('The selected vendor department must belong to the RFQ vendor.')
                )

    @api.onchange('vendor_promised_cost_contact_id')
    def _onchange_vendor_promised_cost_contact_id(self):
        for order in self:
            department_contact = order.vendor_promised_cost_contact_id
            _logger.debug(
                "RFQ vendor contact changed order_id=%s contact_line_id=%s contact_id=%s vendor_id=%s",
                order.id,
                department_contact.id if department_contact else False,
                department_contact.contact_id.id if department_contact else False,
                department_contact.vendor_id.id if department_contact else False,
            )
            if not department_contact:
                order.vendor_promised_cost_contact = False
                continue
            if order.partner_id and department_contact.vendor_id != order.partner_id:
                order.vendor_promised_cost_contact_id = False
                order.vendor_promised_cost_contact = False
                raise ValidationError(
                    _('The selected contact must belong to the RFQ vendor.')
                )
            order.vendor_contact_department_id = department_contact.department_id
            order.vendor_promised_cost_contact = (
                order._purchase_vendor_contact_snapshot(department_contact)
            )

    @api.constrains(
        'partner_id',
        'vendor_contact_department_id',
        'vendor_promised_cost_contact_id',
    )
    def _check_vendor_contact_selector_consistency(self):
        for order in self:
            vendor = order.partner_id
            department = order.vendor_contact_department_id
            department_contact = order.vendor_promised_cost_contact_id
            if vendor and department and department.vendor_id != vendor:
                raise ValidationError(
                    _('The vendor department must belong to the selected vendor.')
                )
            if vendor and department_contact and department_contact.vendor_id != vendor:
                raise ValidationError(
                    _('The vendor contact must belong to the selected vendor.')
                )

    @api.model_create_multi
    def create(self, vals_list):
        synced_vals_list = [
            self._sync_purchase_vendor_contact_values(vals)
            for vals in vals_list
        ]
        orders = super().create(synced_vals_list)
        _logger.debug(
            "RFQ vendor contact selector create order_ids=%s",
            orders.ids,
        )
        return orders

    def write(self, vals):
        synced_vals = self._sync_purchase_vendor_contact_values(vals)
        result = super().write(synced_vals)
        if {
            'partner_id',
            'vendor_contact_department_id',
            'vendor_promised_cost_contact_id',
        } & set(vals):
            _logger.debug(
                "RFQ vendor contact selector write order_ids=%s vals_keys=%s",
                self.ids,
                sorted(vals),
            )
        return result
