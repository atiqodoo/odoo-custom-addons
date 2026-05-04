# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class RetintAnalytics(models.Model):
    """
    RE-TINTING ANALYTICS TRACKING
    
    Tracks every re-tinting operation for quality control, cost analysis,
    and business intelligence.
    
    Use cases:
    - Identify colors/formulas with high re-tint rates
    - Track company vs customer liability costs
    - Monitor quality issues and training needs
    - Analyze re-tinting reasons and patterns
    """
    _name = 'retint.analytics'
    _description = 'Re-Tinting Analytics Tracking'
    _order = 'create_date desc'

    # ============================================================
    # PRODUCT INFORMATION
    # ============================================================
    original_product_id = fields.Many2one(
        'product.product',
        string='Original Product',
        required=True,
        index=True,
        ondelete='restrict',
        help='The tinted product that was returned'
    )
    
    new_product_id = fields.Many2one(
        'product.product',
        string='New Adjusted Product',
        required=True,
        index=True,
        ondelete='restrict',
        help='The new adjusted product created'
    )
    
    colour_code_id = fields.Many2one(
        'colour.code',
        string='Colour Code',
        required=True,
        index=True,
        help='Color that was re-tinted'
    )
    
    fandeck_id = fields.Many2one(
        'colour.fandeck',
        string='Fandeck',
        index=True
    )
    
    # ============================================================
    # MANUFACTURING RECORDS
    # ============================================================
    bom_id = fields.Many2one(
        'mrp.bom',
        string='BOM',
        ondelete='restrict',
        help='BOM created for re-tinting'
    )
    
    mo_id = fields.Many2one(
        'mrp.production',
        string='Manufacturing Order',
        ondelete='restrict',
        help='MO created for re-tinting'
    )
    
    adjustment_number = fields.Integer(
        string='Adjustment Number',
        help='Which adjustment is this? (1, 2, 3, etc.)'
    )
    
    # ============================================================
    # LIABILITY INFORMATION
    # ============================================================
    liability_type = fields.Selection([
        ('customer', 'Customer Liability'),
        ('company', 'Company Liability'),
        ('shared', 'Shared Liability')
    ], string='Liability Type', required=True, index=True)
    
    customer_liability_percent = fields.Float(
        string='Customer Liability %',
        digits=(5, 2),
        group_operator='avg'
    )
    
    company_liability_percent = fields.Float(
        string='Company Liability %',
        digits=(5, 2),
        group_operator='avg'
    )
    
    liability_reason = fields.Selection([
        ('customer_preference', 'Customer Changed Mind / Preference'),
        ('wrong_color_ordered', 'Customer Ordered Wrong Color'),
        ('company_error_formula', 'Company Error: Wrong Formula'),
        ('company_error_mixing', 'Company Error: Mixing/Dispensing Error'),
        ('company_error_machine', 'Company Error: Machine Calibration'),
        ('quality_issue', 'Quality Issue / Product Defect'),
        ('mutual_agreement', 'Mutual Agreement / Goodwill'),
        ('other', 'Other')
    ], string='Reason', required=True, index=True)
    
    # ============================================================
    # COST TRACKING
    # ============================================================
    original_cost = fields.Float(
        string='Original Product Cost',
        digits='Product Price',
        help='Cost of original returned product'
    )
    
    additional_colorant_cost = fields.Float(
        string='Additional Colorant Cost',
        digits='Product Price',
        help='Cost of additional colorants added'
    )
    
    service_cost = fields.Float(
        string='Service Cost',
        digits='Product Price',
        help='Re-tinting service charge'
    )
    
    total_retint_cost = fields.Float(
        string='Total Re-Tinting Cost',
        digits='Product Price',
        help='Colorants + Service cost'
    )
    
    customer_charged = fields.Float(
        string='Customer Charged',
        digits='Product Price',
        help='Amount charged to customer',
        group_operator='sum'
    )
    
    company_absorbed = fields.Float(
        string='Company Absorbed',
        digits='Product Price',
        help='Cost absorbed by company',
        group_operator='sum'
    )
    
    new_product_cost = fields.Float(
        string='New Product Cost',
        digits='Product Price',
        help='Final cost of adjusted product'
    )
    
    new_selling_price = fields.Float(
        string='New Selling Price',
        digits='Product Price',
        help='Selling price of adjusted product'
    )
    
    # ============================================================
    # COLORANT DETAILS
    # ============================================================
    colorants_added_json = fields.Text(
        string='Colorants Added (JSON)',
        help='JSON data of additional colorants added'
    )
    
    # ============================================================
    # NOTES & METADATA
    # ============================================================
    notes = fields.Text(string='Notes')
    
    create_date = fields.Datetime(
        string='Re-Tint Date',
        readonly=True,
        index=True
    )
    
    create_uid = fields.Many2one(
        'res.users',
        string='Created By',
        readonly=True
    )
    
    # ============================================================
    # COMPUTED FIELDS FOR REPORTING
    # ============================================================
    is_company_error = fields.Boolean(
        string='Company Error',
        compute='_compute_is_company_error',
        store=True,
        help='True if re-tint was due to company error'
    )
    
    is_customer_fault = fields.Boolean(
        string='Customer Fault',
        compute='_compute_is_customer_fault',
        store=True,
        help='True if re-tint was due to customer action'
    )
    
    month = fields.Char(
        string='Month',
        compute='_compute_period',
        store=True,
        help='Month in YYYY-MM format'
    )
    
    week = fields.Char(
        string='Week',
        compute='_compute_period',
        store=True,
        help='Week in YYYY-WW format'
    )
    
    @api.depends('liability_reason')
    def _compute_is_company_error(self):
        """Flag if re-tint was due to company error"""
        company_errors = [
            'company_error_formula',
            'company_error_mixing',
            'company_error_machine',
            'quality_issue'
        ]
        for record in self:
            record.is_company_error = record.liability_reason in company_errors
    
    @api.depends('liability_reason')
    def _compute_is_customer_fault(self):
        """Flag if re-tint was due to customer action"""
        customer_reasons = [
            'customer_preference',
            'wrong_color_ordered'
        ]
        for record in self:
            record.is_customer_fault = record.liability_reason in customer_reasons
    
    @api.depends('create_date')
    def _compute_period(self):
        """Compute month and week for grouping"""
        for record in self:
            if record.create_date:
                record.month = record.create_date.strftime('%Y-%m')
                # ISO week number
                record.week = record.create_date.strftime('%Y-W%V')
            else:
                record.month = False
                record.week = False