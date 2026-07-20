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
    lpo_report_show_cost = fields.Boolean(
        string='Show LPO/RFQ Unit Cost',
        config_parameter='purchase_net_price_compute.lpo_report_show_cost',
        default=False,
    )
    lpo_report_show_discount = fields.Boolean(
        string='Show LPO/RFQ Discount',
        config_parameter='purchase_net_price_compute.lpo_report_show_discount',
        default=False,
    )
    lpo_report_show_tax = fields.Boolean(
        string='Show LPO/RFQ Tax/VAT',
        config_parameter='purchase_net_price_compute.lpo_report_show_tax',
        default=False,
    )
    lpo_report_show_subtotal = fields.Boolean(
        string='Show LPO/RFQ Subtotal',
        config_parameter='purchase_net_price_compute.lpo_report_show_subtotal',
        default=False,
    )
    lpo_report_show_total = fields.Boolean(
        string='Show LPO/RFQ Totals',
        config_parameter='purchase_net_price_compute.lpo_report_show_total',
        default=False,
    )
    lpo_report_show_promotion = fields.Boolean(
        string='Show LPO/RFQ Promotion Column',
        config_parameter='purchase_net_price_compute.lpo_report_show_promotion',
        default=False,
    )
    lpo_report_show_grade_volume = fields.Boolean(
        string='Show LPO/RFQ Grade Volume',
        config_parameter='purchase_net_price_compute.lpo_report_show_grade_volume',
        default=False,
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

    rfq_vendor_contact_usage_months = fields.Integer(
        string='Vendor Contact Usage Period',
        config_parameter='purchase_net_price_compute.rfq_vendor_contact_usage_months',
        default=6,
        help=(
            'Number of previous months of RFQs to inspect when prioritizing '
            'vendor sales/customer service contacts. Set to 0 to skip usage '
            'ranking and show primary contacts first.'
        ),
    )
