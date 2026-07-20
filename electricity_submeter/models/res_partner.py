# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    electricity_meter_ids = fields.One2many(
        'electricity.meter', 
        'partner_id', 
        string='Sub-Meters'
    )
    electricity_meter_count = fields.Integer(
        string='Sub-Meter Count', 
        compute='_compute_electricity_meter_count'
    )

    @api.depends('electricity_meter_ids')
    def _compute_electricity_meter_count(self):
        for partner in self:
            partner.electricity_meter_count = len(partner.electricity_meter_ids)
