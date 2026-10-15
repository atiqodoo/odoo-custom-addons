# vendor_price_check/models/vendor_price_discrepancy.py
from odoo import api, fields, models, _

class VendorPriceDiscrepancy(models.Model):
    _name = 'vendor.price.discrepancy'
    _description = 'Vendor Price Discrepancy'

    bill_id = fields.Many2one('account.move', string='Bill', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True)
    vendor_price = fields.Float(string='Current Final Unit Price (Incl. VAT)', required=True)
    lowest_price = fields.Float(string='Lowest Historical Final Unit Price (Incl. VAT)')
    average_price = fields.Float(string='Average Historical Final Unit Price (Incl. VAT)')
    price_difference_lowest = fields.Float(string='Difference from Lowest Final Unit Price')
    percentage_diff_lowest = fields.Float(string='Percentage Difference from Lowest')
    percentage_diff_lowest_display = fields.Char(
        string='Percentage Difference from Lowest',
        compute='_compute_percentage_diff_display',
    )
    price_difference_average = fields.Float(string='Difference from Average Final Unit Price')
    percentage_diff_average = fields.Float(string='Percentage Difference from Average')
    percentage_diff_average_display = fields.Char(
        string='Percentage Difference from Average',
        compute='_compute_percentage_diff_display',
    )
    bill_count = fields.Integer(string='Bill Count', default=1)
    discrepancy_date = fields.Date(string='Date', default=fields.Date.context_today)
    lowest_bill_id = fields.Many2one(
        'account.move',
        string='Lowest Posted Bill',
        readonly=True,
    )
    historical_bill_ids = fields.Many2many(
        'account.move',
        'vendor_price_discrepancy_historical_bill_rel',
        'discrepancy_id',
        'bill_id',
        string='Posted Bills Used for Average',
        readonly=True,
    )
    history_line_ids = fields.One2many(
        'vendor.price.discrepancy.history',
        'discrepancy_id',
        string='Historical Posted Bill Lines',
        readonly=True,
    )

    @api.depends('percentage_diff_lowest', 'percentage_diff_average')
    def _compute_percentage_diff_display(self):
        for discrepancy in self:
            discrepancy.percentage_diff_lowest_display = (
                self._format_percentage_diff(discrepancy.percentage_diff_lowest)
            )
            discrepancy.percentage_diff_average_display = (
                self._format_percentage_diff(discrepancy.percentage_diff_average)
            )

    @staticmethod
    def _format_percentage_diff(value):
        return '%.2f%%' % (value or 0.0)

    def action_open_lowest_bill(self):
        self.ensure_one()
        if not self.lowest_bill_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lowest Posted Bill'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.lowest_bill_id.id,
            'target': 'current',
        }

    def action_view_historical_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Posted Bills Used for Average'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.historical_bill_ids.ids)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
            },
        }


class VendorPriceDiscrepancyHistory(models.Model):
    _name = 'vendor.price.discrepancy.history'
    _description = 'Vendor Price Discrepancy Historical Bill Line'
    _order = 'invoice_date desc, bill_id desc, id desc'

    discrepancy_id = fields.Many2one(
        'vendor.price.discrepancy',
        string='Price Discrepancy',
        required=True,
        ondelete='cascade',
    )
    bill_id = fields.Many2one(
        'account.move',
        string='Posted Bill',
        required=True,
        readonly=True,
    )
    bill_line_id = fields.Many2one(
        'account.move.line',
        string='Posted Bill Line',
        required=True,
        readonly=True,
    )
    invoice_date = fields.Date(string='Bill Date', readonly=True)
    final_unit_price_vat_incl = fields.Float(
        string='Final Unit Price (Incl. VAT) Used for Average',
        readonly=True,
    )

    def action_open_bill(self):
        self.ensure_one()
        if not self.bill_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Posted Bill'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.bill_id.id,
            'target': 'current',
        }
