from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lpo_rubber_stamp_png = fields.Binary(
        related='company_id.lpo_rubber_stamp_png',
        readonly=False,
    )
    lpo_rubber_stamp_filename = fields.Char(
        related='company_id.lpo_rubber_stamp_filename',
        readonly=False,
    )

    rfq_bill_price_check_count = fields.Integer(
        string='Bills to Check for RFQ Cost',
        config_parameter='purchase_net_price_compute.rfq_bill_price_check_count',
        default=3,
        help=(
            'Number of recent posted vendor bills to check when selecting a '
            'product variant on an RFQ. The lowest historical bill price will '
            'be used as the RFQ unit cost.'
        ),
    )
