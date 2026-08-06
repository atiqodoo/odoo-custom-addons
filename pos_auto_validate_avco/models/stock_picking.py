# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    """
    Hooks into _action_done() to trigger AVCO-aware POS dispatch.

    Two triggers:
      1. Purchase receipt   — picking_type_code='incoming', location_id.usage='supplier'
      2. Customer return    — location_id.usage='customer'  (COD or standard, no distinction)

    AVCO timing guarantee:
      avco_before is read BEFORE super() (pre-receipt AVCO).
      avco_after  is read AFTER  super() (post-receipt AVCO, including pos_neg_stock_anglosaxon
      vacuum corrections and standard_price update).
      Outgoing deliveries are then validated at avco_after, ensuring correct COGS entries.

    Error isolation:
      Exceptions in our dispatch logic are caught and logged; they never
      bubble up to block the original stock operation.
    """

    _inherit = 'stock.picking'

    def _action_done(self):
        # ── Step 1: snapshot products + AVCO BEFORE the operation ────────────
        receipt_snap = {}   # {picking_id: {product_id: standard_price}}
        return_snap  = {}

        for picking in self:
            # Only snapshot pickings that are not yet done
            if picking.state == 'done':
                continue

            products = picking.move_ids.filtered(
                lambda m: m.state not in ['done', 'cancel']
            ).mapped('product_id')

            if not products:
                continue

            avco_snap = {p.id: p.standard_price for p in products}

            if (picking.picking_type_code == 'incoming'
                    and picking.location_id.usage == 'supplier'):
                receipt_snap[picking.id] = avco_snap
                _logger.debug(
                    '[AVS] pre-snap receipt: %s | %d products | AVCO=%s',
                    picking.name, len(products), avco_snap
                )

            elif picking.location_id.usage == 'customer':
                return_snap[picking.id] = avco_snap
                _logger.debug(
                    '[AVS] pre-snap return: %s | %d products | AVCO=%s',
                    picking.name, len(products), avco_snap
                )

        # ── Step 2: run the real validation ──────────────────────────────────
        # This chain runs: our super() → pos_neg_stock_anglosaxon._action_done()
        # → stock._action_done()
        # After this returns: AVCO is updated, SVL entries created, price
        # difference entries posted to 514500 by pos_neg_stock_anglosaxon.
        result = super()._action_done()

        # ── Step 3: read AVCO AFTER and dispatch ─────────────────────────────
        svc = self.env['pos.auto.validate.service']

        for picking in self:
            if picking.state != 'done':
                _logger.debug(
                    '[AVS] picking %s not done after _action_done, skip dispatch',
                    picking.name
                )
                continue

            if picking.id in receipt_snap:
                product_ids = list(receipt_snap[picking.id].keys())
                avco_before = receipt_snap[picking.id]
                avco_after  = {
                    pid: self.env['product.product'].browse(pid).standard_price
                    for pid in product_ids
                }
                _logger.info(
                    '[AVS] receipt dispatch: %s | AVCO before=%s | after=%s',
                    picking.name, avco_before, avco_after
                )
                try:
                    svc.run_on_receipt(picking, avco_before, avco_after)
                except Exception:
                    _logger.exception(
                        '[AVS] run_on_receipt error for %s — original operation unaffected',
                        picking.name
                    )

            elif picking.id in return_snap:
                product_ids = list(return_snap[picking.id].keys())
                avco_before = return_snap[picking.id]
                avco_after  = {
                    pid: self.env['product.product'].browse(pid).standard_price
                    for pid in product_ids
                }
                _logger.info(
                    '[AVS] return dispatch: %s | AVCO before=%s | after=%s',
                    picking.name, avco_before, avco_after
                )
                try:
                    svc.run_on_return(picking, avco_before, avco_after)
                except Exception:
                    _logger.exception(
                        '[AVS] run_on_return error for %s — original operation unaffected',
                        picking.name
                    )

        return result
