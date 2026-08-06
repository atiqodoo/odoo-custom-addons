import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class VendorPromotionFocReceiptLog(models.Model):
    _name = 'vendor.promotion.foc.receipt.log'
    _description = 'Vendor Promotion FOC Receipt Log'
    _order = 'receipt_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(required=True, readonly=True, copy=False, index=True)
    application_id = fields.Many2one(
        'vendor.purchase.promotion.application',
        required=True,
        readonly=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, index=True)
    purchase_id = fields.Many2one('purchase.order', required=True, readonly=True, index=True)
    promotion_id = fields.Many2one('vendor.purchase.promotion', required=True, readonly=True, index=True)
    foc_line_id = fields.Many2one('purchase.order.line', required=True, readonly=True, index=True)
    picking_id = fields.Many2one('stock.picking', required=True, readonly=True, index=True)
    move_id = fields.Many2one('stock.move', required=True, readonly=True, index=True, ondelete='cascade')
    expected_product_id = fields.Many2one('product.product', required=True, readonly=True, index=True)
    received_product_id = fields.Many2one('product.product', required=True, readonly=True, index=True)
    product_uom_id = fields.Many2one('uom.uom', required=True, readonly=True)
    received_qty = fields.Float(required=True, readonly=True)
    promised_foc_qty = fields.Float(required=True, readonly=True)
    is_substitute = fields.Boolean(readonly=True, index=True)
    receipt_date = fields.Datetime(readonly=True, index=True)
    vendor_reference_type_id = fields.Many2one(
        'purchase.vendor.reference.type',
        string='Delivery Reference Type',
        readonly=True,
        index=True,
    )
    vendor_reference = fields.Char(string='Delivery Reference', readonly=True, index=True)
    bill_ids = fields.Many2many(
        'account.move',
        'vendor_promotion_foc_receipt_log_bill_rel',
        'log_id',
        'bill_id',
        string='Vendor Bills',
        readonly=True,
    )
    source_model = fields.Char(readonly=True, index=True)
    source_res_id = fields.Integer(readonly=True, index=True)
    source_display_name = fields.Char(readonly=True, index=True)
    details = fields.Json(readonly=True)

    _sql_constraints = [
        (
            'unique_promotion_foc_move_log',
            'UNIQUE(move_id)',
            'A stock move can only be logged once as a promotion FOC receipt.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        _logger.info(
            '[VPP_RECEIPT_LOG] created log_ids=%s application_ids=%s picking_ids=%s move_ids=%s',
            records.ids,
            records.mapped('application_id').ids,
            records.mapped('picking_id').ids,
            records.mapped('move_id').ids,
        )
        return records

    def write(self, vals):
        result = super().write(vals)
        _logger.info(
            '[VPP_RECEIPT_LOG] updated log_ids=%s vals_keys=%s user_id=%s',
            self.ids,
            sorted(vals),
            self.env.user.id,
        )
        return result
