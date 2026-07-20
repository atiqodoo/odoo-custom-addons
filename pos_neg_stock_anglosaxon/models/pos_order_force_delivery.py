# -*- coding: utf-8 -*-
"""Non-blocking POS delivery force-validation after order finalisation.

This file is intentionally additive.  It does not replace the existing
stock.picking negative-stock logic; it gives POS orders a final post-processing
fallback so related outgoing pickings are forced to Done after the POS order has
already been registered.
"""

import logging

from markupsafe import Markup, escape as html_escape

from odoo import models, tools

_logger = logging.getLogger(__name__)

_LOG = '[NegStock][POS_FORCE_DELIVERY]'


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _process_saved_order(self, draft):
        """Run forced delivery only after standard POS finalisation is complete."""
        result = super()._process_saved_order(draft)

        if self.env.context.get('skip_pos_force_delivery_after_accounting'):
            _logger.debug(
                '%s skipped by context | order_ids=%s | draft=%s',
                _LOG, self.ids, draft,
            )
            return result

        for order in self:
            order._force_pending_pos_deliveries_after_accounting(draft=draft)

        return result

    def _force_pending_pos_deliveries_after_accounting(self, draft=False):
        """Best-effort force validation of pending POS outgoing pickings.

        Business rule:
        - POS order finalisation/accounting has priority.
        - Any related POS outgoing picking still not Done must be force-validated,
          even if that creates negative quants / negative valuation layers.
        - Any delivery error is logged and posted to chatter, but not raised back
          to the POS order sync path.
        """
        self.ensure_one()

        if draft:
            _logger.debug(
                '%s skip draft order | order=%s id=%s state=%s',
                _LOG, self.name, self.id, self.state,
            )
            return

        if self.state == 'cancel':
            _logger.debug(
                '%s skip cancelled order | order=%s id=%s',
                _LOG, self.name, self.id,
            )
            return

        pickings = self._get_pending_pos_force_delivery_pickings()
        _logger.info(
            '%s post-accounting scan | order=%s id=%s state=%s '
            'account_move=%s picking_count=%d pending_outgoing=%d',
            _LOG,
            self.name,
            self.id,
            self.state,
            self.account_move.name if self.account_move else 'N/A',
            len(self.picking_ids),
            len(pickings),
        )

        if not pickings:
            return

        for picking in pickings:
            try:
                with self.env.cr.savepoint():
                    self._force_one_pos_delivery_picking(picking)
            except Exception as exc:
                message = tools.exception_to_unicode(exc)
                _logger.error(
                    '%s FAILED but POS order remains finalised | order=%s id=%s '
                    'picking=%s id=%s state=%s error=%s',
                    _LOG,
                    self.name,
                    self.id,
                    picking.name,
                    picking.id,
                    picking.state,
                    message,
                    exc_info=True,
                )
                self._post_force_delivery_failure_note(picking, message)

    def _get_pending_pos_force_delivery_pickings(self):
        """Return linked outgoing POS pickings that still need final validation."""
        self.ensure_one()
        return self.picking_ids.filtered(
            lambda picking: (
                picking.picking_type_code == 'outgoing'
                and picking.state not in ('done', 'cancel')
            )
        )

    def _force_one_pos_delivery_picking(self, picking):
        """Set done quantities to demand and validate with negative stock allowed."""
        self.ensure_one()
        picking.ensure_one()

        moves = picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        _logger.info(
            '%s force start | order=%s id=%s picking=%s id=%s state=%s '
            'moves=%d',
            _LOG,
            self.name,
            self.id,
            picking.name,
            picking.id,
            picking.state,
            len(moves),
        )

        if not moves:
            _logger.warning(
                '%s no active moves | order=%s picking=%s state=%s',
                _LOG, self.name, picking.name, picking.state,
            )
            return

        for move in moves:
            product = move.product_id
            demanded = move.product_uom_qty
            available = product.qty_available
            avco = product.standard_price

            _logger.info(
                '%s force move | order=%s picking=%s move_id=%s product="%s" '
                'demand=%.4f current_done=%.4f qty_available=%.4f avco=%.6f '
                'will_go_negative=%s',
                _LOG,
                self.name,
                picking.name,
                move.id,
                product.display_name,
                demanded,
                move.quantity,
                available,
                avco,
                available < demanded,
            )

            if move.quantity < demanded:
                move.quantity = demanded
            move.picked = True

        picking.with_context(
            cancel_backorder=True,
            skip_immediate=True,
            skip_backorder=True,
            skip_activity_done=True,
            pos_allow_negative_stock=True,
        )._action_done()

        self.env.flush_all()
        picking.invalidate_recordset(['state'])

        _logger.info(
            '%s force done | order=%s id=%s picking=%s id=%s final_state=%s',
            _LOG,
            self.name,
            self.id,
            picking.name,
            picking.id,
            picking.state,
        )

        self._tag_force_delivery_negative_svls(picking)
        self._post_force_delivery_success_note(picking)

    def _tag_force_delivery_negative_svls(self, picking):
        """Tag negative valuation layers created by this forced POS delivery."""
        self.ensure_one()
        picking.ensure_one()

        neg_svls = self.env['stock.valuation.layer'].search([
            ('stock_move_id', 'in', picking.move_ids.ids),
            ('quantity', '<', 0),
            ('pos_negative_origin', '=', False),
        ])

        _logger.info(
            '%s negative SVL scan | order=%s picking=%s move_ids=%s '
            'untagged_negative_layers=%d',
            _LOG,
            self.name,
            picking.name,
            picking.move_ids.ids,
            len(neg_svls),
        )

        for svl in neg_svls:
            svl.write({
                'pos_negative_origin': True,
                'pos_order_id': self.id,
            })
            _logger.info(
                '%s tagged negative SVL | order=%s picking=%s svl_id=%s '
                'product="%s" qty=%.4f unit_cost=%.6f value=%.4f',
                _LOG,
                self.name,
                picking.name,
                svl.id,
                svl.product_id.display_name,
                svl.quantity,
                svl.unit_cost,
                svl.value,
            )

    def _post_force_delivery_success_note(self, picking):
        self.ensure_one()
        picking.ensure_one()
        body = Markup(
            '<b>POS delivery force-validation completed.</b><br/>'
            'This happened after POS order finalisation/accounting. '
            'Negative stock was allowed for this operation when needed.<br/>'
            '<b>Picking:</b> %s<br/>'
            '<b>Final state:</b> %s'
        ) % (
            html_escape(picking.name),
            html_escape(picking.state),
        )
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

    def _post_force_delivery_failure_note(self, picking, error_message):
        self.ensure_one()
        picking.ensure_one()
        body = Markup(
            '<b>POS delivery force-validation failed after order finalisation.</b><br/>'
            'The POS order was kept finalised. Review the picking manually.<br/>'
            '<b>Picking:</b> %s<br/>'
            '<b>State:</b> %s<br/>'
            '<b>Error:</b> <code>%s</code>'
        ) % (
            html_escape(picking.name),
            html_escape(picking.state),
            html_escape((error_message or '')[:500]),
        )
        self.message_post(body=body, subtype_xmlid='mail.mt_note')
