# -*- coding: utf-8 -*-

from odoo import fields, models


class PosAutoPriceLog(models.Model):
    _name = "pos.auto.variant.price.log"
    _description = "POS Auto Variant Price Change Log"
    _order = "create_date desc, id desc"

    name = fields.Char(readonly=True, default="Auto Price Check")
    product_id = fields.Many2one("product.product", required=True, readonly=True, index=True)
    product_tmpl_id = fields.Many2one(
        "product.template",
        related="product_id.product_tmpl_id",
        readonly=True,
        store=True,
        index=True,
    )
    company_id = fields.Many2one("res.company", readonly=True, index=True)
    pos_config_id = fields.Many2one("pos.config", readonly=True)
    changed_by_id = fields.Many2one("res.users", string="Changed By", readonly=True, index=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    trigger = fields.Selection(
        [
            ("receipt", "Incoming Receipt"),
            ("landed_cost", "Landed Cost"),
            ("vendor_bill", "Vendor Bill"),
            ("manual_cost", "Manual Cost Change"),
            ("cost_write", "Cost Write"),
        ],
        required=True,
        readonly=True,
    )
    status = fields.Selection(
        [
            ("adjusted", "Selling Price Adjusted"),
            ("no_increase", "No Cost Increase"),
            ("duplicate", "Already Processed"),
            ("disabled", "Disabled by Configuration"),
            ("invalid_rule", "Invalid Rule"),
            ("error", "Error"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    source_model = fields.Char(readonly=True)
    source_res_id = fields.Integer(readonly=True)
    source_name = fields.Char(readonly=True)
    old_cost = fields.Float(string="Old Cost Excl. VAT", readonly=True, digits="Product Price")
    new_cost = fields.Float(string="New Cost Excl. VAT", readonly=True, digits="Product Price")
    old_inclusive_cost = fields.Float(readonly=True, digits="Product Price")
    new_inclusive_cost = fields.Float(readonly=True, digits="Product Price")
    cost_difference = fields.Float(readonly=True, digits="Product Price")
    rounded_increase = fields.Float(readonly=True, digits="Product Price")
    old_sale_price = fields.Float(readonly=True, digits="Product Price")
    new_sale_price = fields.Float(readonly=True, digits="Product Price")
    old_pricelist_price = fields.Float(readonly=True, digits="Product Price")
    new_pricelist_price = fields.Float(readonly=True, digits="Product Price")
    pricelist_item_id = fields.Many2one("product.pricelist.item", readonly=True)
    old_profit_amount = fields.Float(readonly=True, digits="Product Price")
    new_profit_amount = fields.Float(readonly=True, digits="Product Price")
    profit_amount_change = fields.Float(readonly=True, digits="Product Price")
    old_profit_percent = fields.Float(
        string="Old Profit %",
        readonly=True,
        help="Old profit margin percentage: old profit amount divided by old selling price.",
    )
    new_profit_percent = fields.Float(
        string="New Profit %",
        readonly=True,
        help="New profit margin percentage after rounded increase: new profit amount divided by new selling price.",
    )
    profit_percent_change = fields.Float(string="Profit % Change", readonly=True)
    rounding_step = fields.Float(readonly=True, digits="Product Price")
    vat_rate = fields.Float(readonly=True)
    include_vat = fields.Boolean(readonly=True)
    message = fields.Text(readonly=True)
