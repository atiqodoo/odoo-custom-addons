from odoo import api, models


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    def _notify_pos_price_change(self, pricelists):
        configs = self.env["pos.config"].sudo().search([])
        for config in configs:
            # A base-pricelist change also affects dependent pricelists.
            lists, pending = config._get_available_pricelists(), config._get_available_pricelists()
            while pending:
                bases = pending.item_ids.base_pricelist_id - lists
                lists |= bases
                pending = bases
            if lists & pricelists:
                config._notify_variant_prices()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._notify_pos_price_change(records.pricelist_id)
        return records

    def write(self, vals):
        old_lists = self.pricelist_id
        result = super().write(vals)
        self._notify_pos_price_change(old_lists | self.pricelist_id)
        return result

    def unlink(self):
        lists = self.pricelist_id
        result = super().unlink()
        self._notify_pos_price_change(lists)
        return result
