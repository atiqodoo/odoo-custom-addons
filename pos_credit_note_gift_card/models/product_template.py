# -*- coding: utf-8 -*-
"""
product_template.py — Non-returnable product flag
==================================================
Adds ``pos_not_returnable`` to ``product.template`` (where product
master-data flags belong in Odoo) and bridges the field into the POS
browser payload via the ``product.product`` data-loader.

How Odoo POS loads products
---------------------------
POS loads ``product.product`` (the variant) via
``product.product._load_pos_data_fields()``, NOT ``product.template``.
``product.template`` is only loaded for its ``id`` (returns ``['id']``).

Because ``product.product`` inherits from ``product.template`` through
Odoo's delegation inheritance, ``product.product.pos_not_returnable``
exists and maps directly to the template field — so adding the field
name to ``product.product._load_pos_data_fields`` is all that is
needed to ship it to the browser.

Classes in this file
--------------------
ProductTemplate  — declares the field on the template model.
ProductProduct   — overrides _load_pos_data_fields so POS includes it.
"""

import logging
from odoo import models, fields, api

_logger = logging.getLogger('pos_credit_note_gift_card.product_template')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    pos_not_returnable = fields.Boolean(
        string='Not Returnable in POS',
        default=False,
        help=(
            'When checked, cashiers cannot select this product for a return '
            'or refund from the POS Ticket Screen.\n\n'
            'Typical use: tinted paints, custom-cut materials, service fees.'
        ),
    )


class ProductProduct(models.Model):
    """
    Extends product.product to include pos_not_returnable in the POS
    data payload.

    product.product._load_pos_data_fields() returns an explicit list of
    field names (unlike pos.config / pos.order which return [] = all fields).
    We call super() to get the standard list and append our flag — the
    pattern used by every other POS module that adds product fields.
    """
    _inherit = 'product.product'

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if 'pos_not_returnable' not in fields_list:
            fields_list.append('pos_not_returnable')
            _logger.debug(
                "[ProductProduct][_load_pos_data_fields] "
                "Appended 'pos_not_returnable' for config_id=%s. "
                "Total fields: %d",
                config_id,
                len(fields_list),
            )
        return fields_list
