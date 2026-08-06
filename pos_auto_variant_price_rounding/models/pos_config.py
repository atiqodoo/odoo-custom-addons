# -*- coding: utf-8 -*-

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    auto_variant_price_enabled = fields.Boolean(
        string="Auto Increase Variant Prices",
        default=False,
        help="Automatically increase product variant selling prices when inclusive cost rises.",
    )
    auto_variant_price_rounding_step = fields.Float(
        string="Rounding Step",
        default=50.0,
        help="Cost increases are rounded upward to this amount before updating the selling price.",
    )
    auto_variant_price_include_vat = fields.Boolean(
        string="Include VAT in Cost",
        default=True,
        help="Apply the configured VAT percentage to standard cost before comparing costs.",
    )
    auto_variant_price_vat_rate = fields.Float(
        string="VAT Rate (%)",
        default=16.0,
        help="VAT percentage used to calculate inclusive cost from standard cost.",
    )
    auto_variant_price_on_receipt = fields.Boolean(
        string="Apply on Incoming Receipts",
        default=True,
        help="Apply the formula after supplier incoming deliveries are validated.",
    )
    auto_variant_price_on_landed_cost = fields.Boolean(
        string="Apply on Landed Cost",
        default=True,
        help="Apply the formula after landed costs are validated.",
    )
    auto_variant_price_on_vendor_bill = fields.Boolean(
        string="Apply on Vendor Bill",
        default=True,
        help="Apply the formula after vendor bills are posted and Odoo updates purchase valuation.",
    )
    auto_variant_price_on_manual_cost = fields.Boolean(
        string="Apply on Manual Cost Increase",
        default=True,
        help="Apply the formula when a user manually increases product variant cost.",
    )
    auto_variant_price_update_pricelist = fields.Boolean(
        string="Update POS Pricelist Fixed Price",
        default=True,
        help="When POS uses a fixed pricelist rule, update that rule together with the product sale price.",
    )
    auto_variant_price_pricelist_scope = fields.Selection(
        [
            ("default", "Default POS Pricelist Only"),
            ("available", "All Available POS Pricelists"),
        ],
        string="Pricelist Update Scope",
        default="available",
        help="Choose which POS pricelist rules are updated when a cost increase changes selling price.",
    )
    auto_variant_price_log_no_change = fields.Boolean(
        string="Log No-Change Decisions",
        default=True,
        help="Create audit records when the app checks a cost change but does not update the price.",
    )
