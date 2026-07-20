import logging

from odoo import fields, models, _
from odoo.exceptions import ValidationError

from .res_partner import VENDOR_PROFILE_GAMMA


_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    vendor_invoice_profile = fields.Selection(
        related='partner_id.vendor_invoice_profile',
        string='Vendor Profile',
        readonly=True,
    )
    promotion_application_ids = fields.One2many(
        'vendor.purchase.promotion.application',
        'purchase_id',
        string='Promotion Applications',
        readonly=True,
    )
    promotion_application_count = fields.Integer(
        compute='_compute_promotion_application_count',
    )

    def _compute_promotion_application_count(self):
        for order in self:
            order.promotion_application_count = len(order.promotion_application_ids)

    def _get_invoice_wizard_received_qty(self, po_line):
        if po_line.is_promotion_foc:
            _logger.debug(
                '[VPP_BILL] skip_foc_wizard_line po_id=%s line_id=%s received=%s',
                self.id,
                po_line.id,
                po_line.qty_received,
            )
            return 0.0
        return super()._get_invoice_wizard_received_qty(po_line)

    def action_apply_vendor_promotions(self):
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise ValidationError(_('Promotions can only be applied to draft RFQs.'))
        self._sync_vendor_promotions()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vendor Promotions'),
                'message': _('Promotion rules and FOC lines were refreshed.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def _sync_vendor_promotions(self):
        Promotion = self.env['vendor.purchase.promotion']
        for order in self:
            if order.state not in ('draft', 'sent'):
                continue
            charged_lines = order.order_line.filtered(
                lambda line: line.product_id and not line.display_type and not line.is_promotion_foc
            )
            if order.partner_id.vendor_invoice_profile == VENDOR_PROFILE_GAMMA:
                charged_lines._prepare_gamma_pricing()

            for line in charged_lines:
                rule = Promotion.resolve_rule(order, line.product_id, line.product_qty)
                foc_qty = rule.calculate_foc_qty(line.product_qty) if rule else 0.0
                line.with_context(skip_rfq_bill_price=True).write({
                    'promotion_id': rule.id if rule else False,
                    'promotion_foc_qty': foc_qty,
                })
                existing_foc = line.promotion_foc_line_ids.filtered(
                    lambda child: child.order_id == order
                )[:1]

                if not rule or foc_qty <= 0:
                    if existing_foc:
                        _logger.info(
                            '[VPP_FOC] remove_draft_foc po_id=%s charged_line_id=%s foc_line_id=%s',
                            order.id,
                            line.id,
                            existing_foc.id,
                        )
                        existing_foc.unlink()
                    continue

                foc_vals = {
                    'order_id': order.id,
                    'product_id': line.product_id.id,
                    'name': _('[FOC] %(product)s - %(promotion)s') % {
                        'product': line.product_id.display_name,
                        'promotion': rule.name,
                    },
                    'product_qty': foc_qty,
                    'product_uom': line.product_uom.id,
                    'price_unit': 0.0,
                    'discount': 0.0,
                    'taxes_id': [(5, 0, 0)],
                    'date_planned': line.date_planned,
                    'is_promotion_foc': True,
                    'promotion_parent_line_id': line.id,
                    'promotion_id': rule.id,
                    'promotion_foc_qty': 0.0,
                    'sequence': line.sequence + 1,
                }
                if existing_foc:
                    existing_foc.with_context(skip_rfq_bill_price=True).write(foc_vals)
                    foc_line = existing_foc
                    action = 'updated'
                else:
                    foc_line = self.env['purchase.order.line'].with_context(
                        skip_rfq_bill_price=True
                    ).create(foc_vals)
                    action = 'created'
                _logger.info(
                    '[VPP_FOC] %s po_id=%s promotion_id=%s charged_line_id=%s charged_qty=%s '
                    'foc_line_id=%s foc_qty=%s product_id=%s',
                    action,
                    order.id,
                    rule.id,
                    line.id,
                    line.product_qty,
                    foc_line.id,
                    foc_qty,
                    line.product_id.id,
                )

    def _create_promotion_applications(self):
        Application = self.env['vendor.purchase.promotion.application']
        for order in self:
            for charged_line in order.order_line.filtered(
                lambda line: line.promotion_id
                and not line.is_promotion_foc
                and line.promotion_foc_qty > 0
            ):
                foc_line = charged_line.promotion_foc_line_ids[:1]
                if not foc_line:
                    raise ValidationError(
                        _('Promotion FOC line is missing for %s.') % charged_line.product_id.display_name
                    )
                existing = Application.search([('charged_line_id', '=', charged_line.id)], limit=1)
                if existing:
                    continue
                rule = charged_line.promotion_id
                snapshot = {
                    'promotion_id': rule.id,
                    'promotion_name': rule.name,
                    'calculation_profile': rule.calculation_profile,
                    'charged_qty': charged_line.product_qty,
                    'promised_foc_qty': foc_line.product_qty,
                    'buy_qty': rule.buy_qty,
                    'free_qty': rule.free_qty,
                    'repeat_offer': rule.repeat_offer,
                    'discount_percentage': charged_line.gamma_discount_percentage,
                    'tint_type': charged_line.gamma_tint_type,
                    'tint_percentage': charged_line.gamma_tint_percentage,
                }
                Application.create({
                    'company_id': order.company_id.id,
                    'partner_id': order.partner_id.commercial_partner_id.id,
                    'promotion_id': rule.id,
                    'purchase_id': order.id,
                    'charged_line_id': charged_line.id,
                    'foc_line_id': foc_line.id,
                    'product_id': charged_line.product_id.id,
                    'charged_qty': charged_line.product_qty,
                    'promised_foc_qty': foc_line.product_qty,
                    'promotion_snapshot': snapshot,
                })

    def button_confirm(self):
        draft_orders = self.filtered(lambda order: order.state in ('draft', 'sent'))
        draft_orders._sync_vendor_promotions()
        result = super().button_confirm()
        draft_orders._create_promotion_applications()
        return result

    def action_view_promotion_applications(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Promotion Applications'),
            'res_model': 'vendor.purchase.promotion.application',
            'view_mode': 'list,form',
            'domain': [('purchase_id', '=', self.id)],
            'context': {'create': False},
        }
