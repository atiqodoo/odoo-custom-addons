from odoo import fields, models

class ProductCategory(models.Model):
    _inherit = 'product.category'

    property_cost_method = fields.Selection(
        selection=[
            ('standard', 'Standard Price'),
            ('fifo', 'First In First Out (FIFO)'),
            ('average', 'Average Cost (AVCO)'),
        ],
        string='Costing Method',
        company_dependent=True,
        default='average',  # Set default to AVCO
        required=True,
        help="""Costing method used for products in this category:\n
            Standard Price: The cost price is fixed and manually updated.\n
            AVCO: The cost price is the weighted average of incoming costs.\n
            FIFO: The cost price is based on the oldest incoming costs first."""
    )

    property_valuation = fields.Selection(
        selection=[
            ('manual_periodic', 'Manual'),
            ('real_time', 'Automated'),
        ],
        string='Inventory Valuation',
        company_dependent=True,
        default='real_time',  # Set default to Automated
        help="""Inventory valuation by Default\n
            Manual: Stock valuation done with Stock Quantities and Manual Stock Valuation\n
            Automated: Stock valuation done in real-time"""
    )