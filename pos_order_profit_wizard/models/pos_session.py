# -*- coding: utf-8 -*-

from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        fields = result["search_params"]["fields"]
        for field_name in ("standard_price", "taxes_id"):
            if field_name not in fields:
                fields.append(field_name)
        return result
