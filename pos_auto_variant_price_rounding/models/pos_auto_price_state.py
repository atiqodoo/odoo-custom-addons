from odoo import fields, models


class PosAutoPriceState(models.Model):
    _name = "pos.auto.variant.price.state"
    _description = "Variant Pricelist Cost Baseline"
    _check_company_auto = True

    product_id = fields.Many2one("product.product", required=True, ondelete="cascade", check_company=True, index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    pricelist_id = fields.Many2one("product.pricelist", required=True, ondelete="cascade", check_company=True)
    last_cost = fields.Float(required=True, digits=(16, 8))

    _sql_constraints = [("variant_pricelist_company_unique", "unique(product_id, pricelist_id, company_id)",
                         "Only one cost baseline is allowed per company, variant and pricelist.")]
