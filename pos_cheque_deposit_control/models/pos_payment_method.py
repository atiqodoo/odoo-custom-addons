from odoo import fields, models


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    pcd_is_cheque = fields.Boolean(
        string="Cheque Deposit Control",
        groups="point_of_sale.group_pos_manager,account.group_account_manager",
        help="Identify a cheque collection method for receipt enforcement. Configure its collection journal/account and the existing uncleared guard mapping.",
    )
