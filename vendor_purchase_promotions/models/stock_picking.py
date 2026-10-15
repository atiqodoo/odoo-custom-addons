import logging

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    promotion_foc_substitution_count = fields.Integer(
        compute='_compute_promotion_foc_substitution_count',
    )

    def _promotion_foc_substitution_moves(self):
        self.ensure_one()
        moves = self.move_ids.filtered(
            lambda move: move.purchase_line_id
            and move.purchase_line_id.is_promotion_foc
            and move.state not in ('done', 'cancel')
            and move.purchase_line_id.promotion_id
            and move.purchase_line_id.promotion_id.effective_substitution_policy() != 'none'
        )
        return moves.sorted(
            key=lambda move: (
                move.purchase_line_id.sequence,
                move.product_id.display_name or '',
                move.purchase_line_id.id,
                move.id,
            )
        )

    def _compute_promotion_foc_substitution_count(self):
        for picking in self:
            picking.promotion_foc_substitution_count = len(
                picking._promotion_foc_substitution_moves()
            ) if picking.id else 0

    def action_open_promotion_foc_substitution(self):
        self.ensure_one()
        moves = self._promotion_foc_substitution_moves()
        _logger.info(
            '[VPP_SUBSTITUTE_OPEN] picking_id=%s picking_name=%s user_id=%s move_ids=%s',
            self.id,
            self.name,
            self.env.user.id,
            moves.ids,
        )
        if not moves:
            raise UserError(_('No eligible promotion FOC receipt line is available for substitution.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Choose FOC Substitute'),
            'res_model': 'vendor.promotion.foc.substitution.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'default_move_id': moves[:1].id,
            },
        }

    def _promotion_restore_foc_backorder_demand(self):
        if self.env.context.get('skip_backorder'):
            return
        for picking in self.filtered(
            lambda item: item.picking_type_code == 'incoming'
            and item.state not in ('done', 'cancel')
            and not item.backorder_id
            and item.picking_type_id.create_backorder != 'never'
        ):
            foc_lines = picking.move_ids.purchase_line_id.filtered(
                lambda line: line.is_promotion_foc and line.product_qty > 0
            )
            for foc_line in foc_lines:
                moves = picking.move_ids.filtered(
                    lambda move: move.purchase_line_id == foc_line
                    and move.state not in ('done', 'cancel')
                )
                if not moves:
                    continue
                total_demand = 0.0
                for move in moves:
                    quantity = move.product_uom_qty or 0.0
                    if (
                        move.product_uom
                        and foc_line.product_uom
                        and move.product_uom.category_id == foc_line.product_uom.category_id
                    ):
                        quantity = move.product_uom._compute_quantity(
                            quantity,
                            foc_line.product_uom,
                            rounding_method='HALF-UP',
                        )
                    total_demand += quantity
                rounding = foc_line.product_uom.rounding or 0.01
                if float_compare(
                    total_demand,
                    foc_line.product_qty,
                    precision_rounding=rounding,
                ) >= 0:
                    continue

                missing_qty = foc_line.product_qty - total_demand
                source_move = moves.filtered(lambda move: move.quantity > 0)[:1] or moves[:1]
                if not (
                    source_move.product_uom
                    and foc_line.product_uom
                    and source_move.product_uom.category_id == foc_line.product_uom.category_id
                ):
                    _logger.warning(
                        '[VPP_FOC_BACKORDER_SKIP] picking_id=%s picking_name=%s foc_line_id=%s '
                        'move_id=%s promised_qty=%s total_move_demand=%s reason=uom_category_mismatch',
                        picking.id,
                        picking.name,
                        foc_line.id,
                        source_move.id,
                        foc_line.product_qty,
                        total_demand,
                    )
                    continue
                missing_move_qty = foc_line.product_uom._compute_quantity(
                    missing_qty,
                    source_move.product_uom,
                    rounding_method='HALF-UP',
                )
                backorder_move = moves.filtered(
                    lambda move: move.product_id == foc_line.product_id
                    and float_compare(
                        move.quantity,
                        0.0,
                        precision_rounding=move.product_uom.rounding or 0.01,
                    ) == 0
                )[:1]
                if backorder_move:
                    old_candidate_demand = backorder_move.product_uom_qty
                    backorder_move.write({
                        'product_uom_qty': missing_move_qty,
                        'quantity': 0.0,
                        'picked': False,
                    })
                    action = 'updated'
                else:
                    old_candidate_demand = 0.0
                    backorder_move = self.env['stock.move'].create({
                        'name': foc_line.product_id.display_name,
                        'product_id': foc_line.product_id.id,
                        'product_uom_qty': missing_move_qty,
                        'quantity': 0.0,
                        'picked': False,
                        'product_uom': source_move.product_uom.id,
                        'picking_id': picking.id,
                        'picking_type_id': picking.picking_type_id.id,
                        'location_id': source_move.location_id.id,
                        'location_dest_id': source_move.location_dest_id.id,
                        'purchase_line_id': foc_line.id,
                        'partner_id': source_move.partner_id.id,
                        'company_id': source_move.company_id.id,
                        'price_unit': 0.0,
                        'origin': source_move.origin,
                        'group_id': source_move.group_id.id,
                        'procure_method': source_move.procure_method,
                        'state': 'draft',
                    })
                    backorder_move._action_confirm()
                    backorder_move.write({'quantity': 0.0, 'picked': False})
                    action = 'created'
                _logger.warning(
                    '[VPP_FOC_BACKORDER_CANDIDATE] action=%s picking_id=%s picking_name=%s foc_line_id=%s '
                    'source_move_id=%s backorder_move_id=%s source_product_id=%s backorder_product_id=%s '
                    'promised_qty=%s total_move_demand_before=%s missing_qty=%s '
                    'old_candidate_demand=%s backorder_move_demand=%s source_done_qty=%s '
                    'backorder_done_qty=%s backorder_picked=%s create_backorder=%s',
                    action,
                    picking.id,
                    picking.name,
                    foc_line.id,
                    source_move.id,
                    backorder_move.id,
                    source_move.product_id.id,
                    backorder_move.product_id.id,
                    foc_line.product_qty,
                    total_demand,
                    missing_qty,
                    old_candidate_demand,
                    backorder_move.product_uom_qty,
                    source_move.quantity,
                    backorder_move.quantity,
                    backorder_move.picked,
                    picking.picking_type_id.create_backorder,
                )

    def button_validate(self):
        self._promotion_restore_foc_backorder_demand()
        result = super().button_validate()
        purchase_lines = self.move_ids.purchase_line_id
        applications = self.env['vendor.purchase.promotion.application'].search([
            '|',
            ('charged_line_id', 'in', purchase_lines.ids),
            ('foc_line_id', 'in', purchase_lines.ids),
        ]) if purchase_lines else self.env['vendor.purchase.promotion.application']
        if applications:
            applications._compute_foc_status()
            applications._sync_foc_receipt_logs(pickings=self)
            applications.bill_ids._sync_promotion_payment_hold()
            for application in applications:
                _logger.info(
                    '[VPP_RECEIPT] validated picking_ids=%s application_id=%s charged_received=%s '
                    'foc_expected=%s foc_received=%s foc_outstanding=%s state=%s bill_ids=%s',
                    self.ids,
                    application.id,
                    application.charged_line_id.qty_received,
                    application.promised_foc_qty,
                    application.received_foc_qty,
                    application.outstanding_foc_qty,
                    application.fulfillment_state,
                    application.bill_ids.ids,
                )
        return result
