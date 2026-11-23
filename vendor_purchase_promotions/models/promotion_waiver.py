import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError


_logger = logging.getLogger(__name__)

WAIVER_TYPES = [
    ('charged_partial', 'Charged Goods Partially Delivered'),
    ('charged_missing', 'Charged Goods Not Delivered'),
    ('foc_partial', 'FOC Partially Delivered'),
    ('foc_missing', 'FOC Not Delivered'),
    ('supplier_delay', 'Supplier Agreed to Deliver Later'),
    ('multiple', 'Multiple Reasons'),
    ('other', 'Other'),
]


class VendorPromotionWaiver(models.Model):
    _name = 'vendor.promotion.waiver'
    _description = 'Vendor Promotion Payment Waiver'
    _order = 'approved_at desc, id desc'
    _rec_name = 'bill_id'

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    bill_id = fields.Many2one('account.move', required=True, readonly=True, index=True, ondelete='restrict')
    purchase_id = fields.Many2one('purchase.order', required=True, readonly=True, index=True, ondelete='restrict')
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True)
    application_id = fields.Many2one('vendor.purchase.promotion.application', required=True, readonly=True, index=True, ondelete='restrict')
    promotion_id = fields.Many2one('vendor.purchase.promotion', required=True, readonly=True, index=True)
    charged_line_ids = fields.Many2many('purchase.order.line', 'vpp_waiver_charged_line_rel', 'waiver_id', 'line_id', readonly=True)
    foc_line_id = fields.Many2one('purchase.order.line', readonly=True)
    picking_ids = fields.Many2many('stock.picking', compute='_compute_related_documents', string='Receipts and Backorders', readonly=True)
    receipt_log_ids = fields.Many2many('vendor.promotion.foc.receipt.log', compute='_compute_related_documents', string='FOC Receipt Logs', readonly=True)
    waiver_type = fields.Selection(WAIVER_TYPES, required=True, readonly=True, index=True)
    reason = fields.Text(required=True, readonly=True)
    approved_by_id = fields.Many2one('res.users', required=True, readonly=True, index=True)
    approved_at = fields.Datetime(required=True, readonly=True, index=True)
    charged_qty = fields.Float(string='Charged Ordered', readonly=True)
    charged_received_qty = fields.Float(string='Charged Received at Approval', readonly=True)
    promised_foc_qty = fields.Float(string='FOC Promised', readonly=True)
    received_foc_qty = fields.Float(string='FOC Received at Approval', readonly=True)
    outstanding_foc_qty = fields.Float(string='FOC Outstanding at Approval', readonly=True)
    fulfillment_state = fields.Selection(related='application_id.fulfillment_state', string='Current FOC Status', readonly=True)

    @api.depends('application_id.charged_line_id.move_ids.picking_id',
                 'application_id.charged_line_ids.move_ids.picking_id',
                 'application_id.foc_line_id.move_ids.picking_id',
                 'application_id.foc_receipt_log_ids')
    def _compute_related_documents(self):
        for waiver in self:
            application = waiver.application_id
            lines = application.charged_line_ids or application.charged_line_id
            waiver.picking_ids = (lines | application.foc_line_id).mapped('move_ids.picking_id')
            waiver.receipt_log_ids = application.foc_receipt_log_ids

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Waiver audit records are created only by the approval workflow.'))

    def write(self, vals):
        raise AccessError(_('Waiver audit records cannot be changed.'))

    def unlink(self):
        raise AccessError(_('Waiver audit records cannot be deleted.'))

    @api.model
    def _record_approved_waivers(self, bill, waiver_type, reason, approved_at):
        bill.ensure_one()
        bill._check_promotion_release_access()
        _logger.debug('[VPP][WAIVER_AUDIT][START] bill_id=%s user_id=%s', bill.id, self.env.uid)
        vals_list = []
        for application in bill.promotion_application_ids:
            lines = application.charged_line_ids or application.charged_line_id
            vals_list.append({
                'company_id': bill.company_id.id, 'bill_id': bill.id,
                'purchase_id': application.purchase_id.id, 'partner_id': application.partner_id.id,
                'application_id': application.id, 'promotion_id': application.promotion_id.id,
                'charged_line_ids': [(6, 0, lines.ids)], 'foc_line_id': application.foc_line_id.id,
                'waiver_type': waiver_type, 'reason': reason, 'approved_by_id': self.env.uid,
                'approved_at': approved_at, 'charged_qty': application.charged_qty,
                'charged_received_qty': application.charged_received_qty,
                'promised_foc_qty': application.promised_foc_qty,
                'received_foc_qty': application.received_foc_qty,
                'outstanding_foc_qty': application.outstanding_foc_qty,
            })
        # Approval is authorized above; audit records are not directly creatable by users.
        records = super(VendorPromotionWaiver, self.sudo()).create(vals_list) if vals_list else self.browse()
        _logger.info('[VPP][WAIVER_AUDIT][END] bill_id=%s waiver_ids=%s', bill.id, records.ids)
        return records
