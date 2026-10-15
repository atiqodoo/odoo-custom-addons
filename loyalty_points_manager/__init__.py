# -*- coding: utf-8 -*-

from . import models
from . import wizard


def post_init_hook(env):
    env.cr.execute("""
        UPDATE res_partner
           SET lpm_can_earn_loyalty_points = TRUE
         WHERE lpm_can_earn_loyalty_points IS NULL
    """)
    env.cr.execute("""
        UPDATE res_partner
           SET lpm_can_redeem_loyalty_points = TRUE
         WHERE lpm_can_redeem_loyalty_points IS NULL
    """)
    env.cr.execute("""
        WITH awarded AS (
            SELECT order_id, MAX(create_date) AS awarded_at
              FROM loyalty_history
             WHERE order_model = 'sale.order'
               AND issued > 0
             GROUP BY order_id
        )
        UPDATE sale_order so
           SET lpm_backend_loyalty_awarded = TRUE,
               lpm_backend_loyalty_awarded_at = awarded.awarded_at
          FROM awarded
         WHERE so.id = awarded.order_id
           AND COALESCE(so.lpm_backend_loyalty_awarded, FALSE) = FALSE
    """)
