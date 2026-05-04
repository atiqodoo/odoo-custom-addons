# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class CourierCompany(models.Model):
    _name = 'courier.company'
    _description = 'Courier Company'
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(
        string='Company Name',
        required=True,
        index=True,
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        help='Link to partner record if this courier is also a vendor',
    )
    
    phone = fields.Char(string='Phone')
    
    mobile = fields.Char(string='Mobile')
    
    email = fields.Char(string='Email')
    
    website = fields.Char(string='Website')
    
    default_journal_id = fields.Many2one(
        'account.journal',
        string='Default Payment Journal',
        domain=[('type', 'in', ['bank', 'cash'])],
        help='Default journal to use when company pays this courier',
    )
    
    notes = fields.Text(string='Notes')
    
    # Statistics
    dispatch_count = fields.Integer(
        string='Total Dispatches',
        compute='_compute_dispatch_count',
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def _compute_dispatch_count(self):
        """Count total dispatches for this courier company"""
        for company in self:
            company.dispatch_count = self.env['courier.dispatch'].search_count([
                ('courier_company_id', '=', company.id)
            ])
    
    def action_view_dispatches(self):
        """View all dispatches for this courier company"""
        self.ensure_one()
        
        return {
            'name': _('Courier Dispatches'),
            'type': 'ir.actions.act_window',
            'res_model': 'courier.dispatch',
            'view_mode': 'list,form,kanban',
            'domain': [('courier_company_id', '=', self.id)],
            'context': {'default_courier_company_id': self.id},
        }
