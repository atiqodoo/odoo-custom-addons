# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class ElectricityMeter(models.Model):
    _name = 'electricity.meter'
    _description = 'Electricity Sub-Meter'
    _order = 'name'

    name = fields.Char(string='Meter Name/Reference', required=True, copy=False)
    partner_id = fields.Many2one(
        'res.partner', 
        string='Neighbor/Customer', 
        required=True, 
        domain="[('customer_rank', '>', 0)]",
        help="The customer/neighbor associated with this sub-meter."
    )
    default_unit_rate = fields.Float(
        string='Default Unit Rate', 
        required=True, 
        default=0.15,
        help="Default price per unit (kWh) to charge this customer."
    )
    product_id = fields.Many2one(
        'product.product', 
        string='Electricity Service Product',
        domain="[('type', '=', 'service')]",
        help="Service product to use for invoicing this meter. If left empty, the default product from Settings will be used."
    )
    last_reading = fields.Float(
        string='Last Confirmed Reading (kWh)', 
        compute='_compute_last_reading', 
        store=True,
        help="The current display value of the sub-meter based on the last confirmed reading."
    )
    reading_ids = fields.One2many(
        'electricity.reading', 
        'meter_id', 
        string='Readings History'
    )
    company_id = fields.Many2one(
        'res.company', 
        string='Company', 
        required=True, 
        default=lambda self: self.env.company
    )

    @api.depends('reading_ids', 'reading_ids.state', 'reading_ids.current_reading')
    def _compute_last_reading(self):
        for record in self:
            _logger.debug("Computing last reading for meter: %s", record.name)
            valid_readings = record.reading_ids.filtered(
                lambda r: r.state in ('measured', 'invoiced')
            ).sorted(key=lambda r: (r.date, r.id), reverse=True)
            
            record.last_reading = valid_readings[0].current_reading if valid_readings else 0.0
            _logger.debug("Meter %s calculated last reading as: %s", record.name, record.last_reading)

    @api.model
    def default_get(self, fields_list):
        res = super(ElectricityMeter, self).default_get(fields_list)
        if 'product_id' in fields_list and not res.get('product_id'):
            # Fetch from global configuration parameter
            param_val = self.env['ir.config_parameter'].sudo().get_param('electricity_submeter.electricity_product_id')
            if param_val:
                try:
                    res['product_id'] = int(param_val)
                    _logger.debug("Set default product %s on new meter from parameters.", param_val)
                except ValueError:
                    _logger.warning("Invalid default product ID configured in settings: %s", param_val)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super(ElectricityMeter, self).create(vals_list)
        for record in records:
            _logger.info("Created new Electricity Sub-Meter: Name: %s, Customer ID: %s, Rate: %s", 
                         record.name, record.partner_id.id, record.default_unit_rate)
        return records

    def write(self, vals):
        res = super(ElectricityMeter, self).write(vals)
        if any(f in vals for f in ['partner_id', 'default_unit_rate', 'product_id']):
            for record in self:
                _logger.info("Updated Electricity Sub-Meter details for: %s (Values: %s)", record.name, vals)
        return res
