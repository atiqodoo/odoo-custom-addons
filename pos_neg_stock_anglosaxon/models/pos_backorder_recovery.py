# -*- coding: utf-8 -*-
"""Recover POS backorders that were created before POS linkage was written.

Odoo validates a real-time POS picking before it writes ``pos_order_id`` and
``pos_session_id`` on that picking.  When only part of a tracked demand can be
completed, the standard stock flow may therefore create an unlinked backorder.
The normal post-accounting force-delivery scan cannot see that child picking.

This extension only broadens that scan to descendants of pickings already
linked to the POS order.  It does not recreate moves, reopen completed
pickings, or implement any valuation/accounting behaviour.  Eligible pending
backorders are given the missing POS metadata and are then handled by the
existing lot-aware force-delivery path.
"""

import logging

from odoo import models


_logger = logging.getLogger(__name__)
_LOG = "[NegStock][POS_BACKORDER_RECOVERY]"


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _get_pending_pos_force_delivery_pickings(self):
        """Include eligible pending descendants of this order's POS pickings."""
        self.ensure_one()

        pending = super()._get_pending_pos_force_delivery_pickings()
        descendants = self._get_pos_force_delivery_backorder_descendants()
        if not descendants:
            return pending

        recovered = self.env["stock.picking"]
        for picking in descendants:
            if not self._is_recoverable_pos_backorder(picking):
                continue
            self._link_recovered_pos_backorder(picking)
            recovered |= picking

        if recovered:
            _logger.info(
                "%s scan expanded | order=%s id=%s direct_pending=%s "
                "recovered_pending=%s",
                _LOG,
                self.name,
                self.id,
                pending.mapped("name"),
                recovered.mapped("name"),
            )

        return pending | recovered

    def _get_pos_force_delivery_backorder_descendants(self):
        """Return the complete backorder chain below directly linked pickings."""
        self.ensure_one()

        Picking = self.env["stock.picking"]
        frontier = self.picking_ids
        descendants = Picking
        visited_ids = set(frontier.ids)

        while frontier:
            children = Picking.search(
                [("backorder_id", "in", frontier.ids)],
                order="id asc",
            ).filtered(lambda picking: picking.id not in visited_ids)
            if not children:
                break

            descendants |= children
            visited_ids.update(children.ids)
            frontier = children

        return descendants

    def _is_recoverable_pos_backorder(self, picking):
        """Keep recovery narrow and never take a picking from another order."""
        self.ensure_one()
        picking.ensure_one()

        if picking.picking_type_code != "outgoing":
            return False
        if picking.state in ("done", "cancel"):
            return False
        if picking.company_id != self.company_id:
            _logger.warning(
                "%s skipped company mismatch | order=%s picking=%s "
                "order_company=%s picking_company=%s",
                _LOG,
                self.name,
                picking.name,
                self.company_id.display_name,
                picking.company_id.display_name,
            )
            return False
        if picking.pos_order_id and picking.pos_order_id != self:
            _logger.warning(
                "%s skipped foreign POS link | order=%s picking=%s linked_order=%s",
                _LOG,
                self.name,
                picking.name,
                picking.pos_order_id.name,
            )
            return False
        if picking.pos_session_id and picking.pos_session_id != self.session_id:
            _logger.warning(
                "%s skipped foreign POS session | order=%s picking=%s "
                "linked_session=%s",
                _LOG,
                self.name,
                picking.name,
                picking.pos_session_id.name,
            )
            return False
        return True

    def _link_recovered_pos_backorder(self, picking):
        """Write only missing POS identity fields on an eligible backorder."""
        self.ensure_one()
        picking.ensure_one()

        values = {}
        if not picking.pos_order_id:
            values["pos_order_id"] = self.id
        if not picking.pos_session_id:
            values["pos_session_id"] = self.session_id.id
        if not picking.origin:
            values["origin"] = self.name

        if values:
            picking.write(values)
            _logger.info(
                "%s linked | order=%s id=%s picking=%s id=%s parent=%s "
                "fields=%s",
                _LOG,
                self.name,
                self.id,
                picking.name,
                picking.id,
                picking.backorder_id.name,
                sorted(values),
            )

