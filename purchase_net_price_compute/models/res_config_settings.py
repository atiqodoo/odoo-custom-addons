from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    _vendor_reference_required_params = {
        'vendor_reference_required_rfq': 'purchase_net_price_compute.vendor_reference_required_rfq',
        'vendor_reference_required_lpo': 'purchase_net_price_compute.vendor_reference_required_lpo',
        'vendor_reference_required_receipt': 'purchase_net_price_compute.vendor_reference_required_receipt',
        'vendor_reference_required_invoice': 'purchase_net_price_compute.vendor_reference_required_invoice',
    }

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
    vendor_reference_required_rfq = fields.Boolean(
        string='RFQ Vendor Reference Required',
        config_parameter='purchase_net_price_compute.vendor_reference_required_rfq',
        default=True,
    )
    vendor_reference_required_lpo = fields.Boolean(
        string='LPO Vendor Reference Required',
        config_parameter='purchase_net_price_compute.vendor_reference_required_lpo',
        default=True,
    )
    vendor_reference_required_receipt = fields.Boolean(
        string='Receipt Vendor Reference Required',
        config_parameter='purchase_net_price_compute.vendor_reference_required_receipt',
        default=True,
    )
    vendor_reference_required_invoice = fields.Boolean(
        string='Vendor Bill Reference Required',
        config_parameter='purchase_net_price_compute.vendor_reference_required_invoice',
        default=True,
    )

    def _get_config_bool(self, key, default=True):
        value = self.env['ir.config_parameter'].sudo().get_param(key)
        if value is False:
            return default
        return str(value).lower() not in ('false', '0', 'no', 'off')

    def get_values(self):
        values = super().get_values()
        values.update({
            field_name: self._get_config_bool(param_key, default=True)
            for field_name, param_key in self._vendor_reference_required_params.items()
        })
        return values

    def set_values(self):
        super().set_values()
        config = self.env['ir.config_parameter'].sudo()
        for field_name, param_key in self._vendor_reference_required_params.items():
            config.set_param(param_key, '1' if self[field_name] else '0')
