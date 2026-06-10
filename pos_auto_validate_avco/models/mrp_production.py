# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    """
    Hooks into button_mark_done() to trigger AVCO-aware POS dispatch
    after a Manufacturing Order is completed.

    AVCO timing:
      For manufactured products, standard_price (AVCO) is recalculated by
      Odoo during button_mark_done() based on actual component + work-centre
      costs.  We capture it before and after super() and pass both snapshots
      to the service so the chatter can show the cost movement.

    Guard:
      If button_mark_done() opens a wizard instead of completing the MO
      (e.g. immediate production dialog), mo.state will not be 'done' after
      super() and we skip cleanly.

    Error isolation:
      Exceptions in dispatch logic are caught and logged; they never bubble
      up to block the manufacturing completion.
    """

    _inherit = 'mrp.production'

    def button_mark_done(self):
        # ── Step 1: snapshot AVCO BEFORE MO completion ───────────────────────
        avco_before_map = {}   # {mo_id: {product_id: standard_price}}

        for mo in self:
            if mo.state == 'done' or not mo.product_id:
                continue
            avco_before_map[mo.id] = {
                mo.product_id.id: mo.product_id.standard_price
            }
            _logger.debug(
                '[AVS] MO pre-snap: %s | product=%s | avco_before=%.4f',
                mo.name,
                mo.product_id.display_name,
                mo.product_id.standard_price,
            )

        # ── Step 2: complete the MO (updates finished-product AVCO) ──────────
        result = super().button_mark_done()

        # ── Step 3: read AVCO AFTER and dispatch POS deliveries ──────────────
        svc = self.env['pos.auto.validate.service']

        for mo in self:
            if mo.state != 'done':
                # Wizard was shown (quantities not set) — MO not finished yet
                _logger.debug(
                    '[AVS] MO %s not done after button_mark_done (wizard?), skip',
                    mo.name
                )
                continue

            if mo.id not in avco_before_map:
                continue

            product = mo.product_id
            if not product:
                continue

            avco_before = avco_before_map[mo.id]
            avco_after  = {product.id: product.standard_price}

            _logger.info(
                '[AVS] MO dispatch: %s | product=%s | AVCO %.4f → %.4f',
                mo.name,
                product.display_name,
                avco_before.get(product.id, 0),
                avco_after[product.id],
            )
            try:
                svc.run_on_manufacturing(mo, avco_before, avco_after)
            except Exception:
                _logger.exception(
                    '[AVS] run_on_manufacturing error for MO %s — original operation unaffected',
                    mo.name
                )

        return result
