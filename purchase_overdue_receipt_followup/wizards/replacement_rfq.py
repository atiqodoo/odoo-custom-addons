import logging

from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class PurchaseReceiptReplacement(models.TransientModel):
    _name = 'purchase.receipt.replacement'
    _description = 'Review overdue supply and request a replacement'
    _check_company_auto = True

    followup_id = fields.Many2one('purchase.receipt.followup', required=True, readonly=True, check_company=True)
    company_id = fields.Many2one(related='followup_id.company_id', store=True)
    product_id = fields.Many2one(related='followup_id.product_id')
    uom_id = fields.Many2one(related='product_id.uom_id')
    overdue_qty = fields.Float(related='followup_id.overdue_qty')
    suggested_qty = fields.Float(related='followup_id.suggested_qty')
    supplier_id = fields.Many2one('product.supplierinfo', string='Vendor Price',
        domain="[('product_tmpl_id', '=', product_tmpl_id), ('product_id', 'in', [False, product_id]), ('company_id', 'in', [False, company_id])]")
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id')
    quantity = fields.Float(string='Replacement Quantity', digits='Product Unit of Measure')
    expected_date = fields.Datetime(string='New Expected Arrival', required=True, default=fields.Datetime.now)
    reason = fields.Text(string='Follow-up / Replacement Reason')
    target_order_id = fields.Many2one('purchase.order', string='Add to Existing Draft RFQ', check_company=True,
        domain="[('state', '=', 'draft'), ('company_id', '=', company_id), ('partner_id', '=', vendor_id)]")
    vendor_id = fields.Many2one(related='supplier_id.partner_id')
    vendor_reference_type_id = fields.Many2one('purchase.vendor.reference.type', string='Vendor Reference Type')
    vendor_reference = fields.Char(string='Vendor Reference')
    vendor_department_id = fields.Many2one('vendor.department', string='Vendor Department',
        domain="[('vendor_id', '=', vendor_id), ('active', '=', True)]")
    vendor_contact_id = fields.Many2one('vendor.department.contact', string='Vendor Contact',
        domain="[('vendor_id', '=', vendor_id), ('department_id', '=', vendor_department_id), ('active', '=', True)]")

    @api.model
    def _open(self, followup):
        followup._check_purchase_access()
        supplier = followup.orderpoint_id.supplier_id or followup.product_id.with_company(
            followup.company_id)._select_seller(quantity=followup.suggested_qty,
                                               uom_id=followup.product_id.uom_id)
        expected = fields.Datetime.add(fields.Datetime.now(), days=supplier.delay if supplier else 0)
        wizard = self.create({'followup_id': followup.id, 'quantity': followup.suggested_qty,
                              'supplier_id': supplier.id, 'expected_date': expected})
        return {'type': 'ir.actions.act_window', 'name': _('Follow Up Overdue Supply'),
                'res_model': self._name, 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}

    def action_compare_stock(self):
        self.ensure_one()
        self.check_access('read')
        return self.followup_id.action_compare_stock()

    def action_open_receipts(self):
        self.ensure_one()
        self.check_access('read')
        return self.followup_id.action_open_receipts()

    def action_open_purchase_orders(self):
        self.ensure_one()
        self.check_access('read')
        return self.followup_id.action_open_purchase_orders()

    def _prepare_order_values(self):
        supplier = self.supplier_id
        op = self.followup_id.orderpoint_id
        company = self.company_id
        rule = op.rule_ids.filtered(lambda item: item.action == 'buy')[:1]
        if not rule:
            raise UserError(_('This rule no longer has a Buy route.'))
        # Standard purchase preparation preserves payment terms, currency, fiscal
        # position and picking type. Actual creation uses current user's rights.
        values = op._prepare_procurement_values(date=self.expected_date)
        values.update(supplier=supplier, date_planned=self.expected_date, date_order=fields.Datetime.now())
        order_values = rule._prepare_purchase_order(company, [_('Overdue follow-up %s') % self.followup_id.id], [values])
        order_values.update({
            'vendor_reference_type_id': self.vendor_reference_type_id.id,
            'partner_ref': self.vendor_reference,
            'vendor_contact_department_id': self.vendor_department_id.id,
            'vendor_promised_cost_contact_id': self.vendor_contact_id.id,
        })
        return order_values, values

    def action_create_rfq(self):
        self.ensure_one()
        self.check_access('read')
        alert = self.followup_id
        alert._check_purchase_access()
        _logger.debug('[OVERDUE_RECEIPT][REPLACEMENT][START] alert_id=%s user_id=%s', alert.id, self.env.uid)
        try:
            # Prevent two users/tabs from authorizing the same replacement.
            self.env.cr.execute('SELECT id FROM purchase_receipt_followup WHERE id = %s FOR UPDATE', [alert.id])
            alert.invalidate_recordset()
            if alert.replacement_order_id and alert.replacement_order_id.state != 'cancel':
                raise UserError(_('A replacement RFQ has already been requested. Open it instead.'))
            op = alert.orderpoint_id
            if not op.active or op.trigger != 'auto' or not self.company_id.receipt_followup_enabled:
                raise UserError(_('Automatic follow-up is no longer enabled for this rule.'))
            now = fields.Datetime.now()
            if not self.env['purchase.receiving.calendar']._is_open(self.company_id, now):
                raise UserError(_('Review overdue supply during receiving working hours.'))
            moves = self.env['purchase.overdue.supply']._moves_by_rule(op, now)[op.id]
            if not moves:
                raise UserError(_('No overdue supplier receipts remain. Refresh the follow-up list.'))
            # Always recompute: stock, RFQs or receipt dates may have changed since popup.
            snapshot = self.env['purchase.overdue.supply']._replacement_snapshot(op, moves)
            rounding = self.product_id.uom_id.rounding
            if float_compare(self.quantity, 0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('Enter a positive replacement quantity.'))
            if float_compare(self.quantity, snapshot['suggested_qty'], precision_rounding=rounding) > 0:
                raise UserError(_('The current maximum replacement quantity is %s. Other supply or stock has changed.') % snapshot['suggested_qty'])
            if not (self.reason or '').strip():
                raise ValidationError(_('Record the vendor follow-up result and why a replacement is needed.'))
            if self.expected_date < now:
                raise ValidationError(_('New expected arrival must not be in the past.'))
            supplier = self.supplier_id
            supplier.check_access('read')
            if (not supplier or supplier.product_tmpl_id != self.product_id.product_tmpl_id
                    or supplier.product_id and supplier.product_id != self.product_id
                    or supplier.company_id and supplier.company_id != self.company_id):
                raise ValidationError(_('Choose a vendor price for this variant and company.'))
            seller = self.product_id.with_company(self.company_id)._select_seller(
                partner_id=supplier.partner_id, quantity=self.quantity,
                date=now.date(), uom_id=self.product_id.uom_id)
            if not seller:
                raise UserError(_('No valid vendor price applies to this quantity and date.'))
            order_values, procurement_values = self._prepare_order_values()
            order = self.target_order_id
            if order:
                order.check_access('write')
                self.env.cr.execute('SELECT id FROM purchase_order WHERE id = %s FOR UPDATE', [order.id])
                order.invalidate_recordset()
                if (order.state != 'draft' or order.company_id != self.company_id
                        or order.partner_id != supplier.partner_id
                        or order.picking_type_id.id != order_values['picking_type_id']):
                    raise ValidationError(_('Choose a draft RFQ for the same vendor, company and receiving operation.'))
            else:
                order = self.env['purchase.order'].with_company(self.company_id).create(order_values)
            line_values = self.env['purchase.order.line']._prepare_purchase_order_line_from_procurement(
                self.product_id, self.quantity, self.product_id.uom_id, op.location_id,
                self.product_id.display_name, order_values['origin'], self.company_id, procurement_values, order)
            self.env['purchase.order.line'].with_company(self.company_id).create(line_values)
            # Alert records are system-maintained/read-only to buyers. Only the
            # validated audit update is elevated; the RFQ above never uses sudo.
            alert.sudo().write(dict(snapshot, state='replaced', replacement_order_id=order.id,
                                    replacement_reason=self.reason.strip(), replacement_user_id=self.env.uid,
                                    replacement_date=now, move_ids=[Command.set(moves.ids)]))
            order.message_post(body=_('Replacement requested for overdue receipt follow-up %s. Original receipts remain open; review them to avoid duplicate delivery.') % alert.id)
            _logger.debug('[OVERDUE_RECEIPT][REPLACEMENT][END] alert_id=%s order_id=%s quantity=%s',
                          alert.id, order.id, self.quantity)
            return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order', 'res_id': order.id,
                    'view_mode': 'form', 'target': 'current'}
        except Exception:
            _logger.exception('[OVERDUE_RECEIPT][REPLACEMENT][ERROR] alert_id=%s user_id=%s', alert.id, self.env.uid)
            raise
