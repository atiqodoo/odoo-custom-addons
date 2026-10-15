# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorBillWizardDisplayMixin(models.AbstractModel):
    _name = 'vendor.bill.wizard.display.mixin'
    _description = 'Vendor Bill Wizard Display Options'

    show_reference_columns = fields.Boolean(
        string='References',
        default=True,
        help='Show optional PO/reference columns in bill wizard lines.',
    )
    show_computed_line_columns = fields.Boolean(
        string='Computed Prices',
        default=False,
        help='Show optional computed price columns in bill wizard lines.',
    )
    show_vat_line_columns = fields.Boolean(
        string='VAT Values',
        default=True,
        help='Show optional VAT-inclusive computed columns in bill wizard lines.',
    )
    show_promised_cost_columns = fields.Boolean(
        string='Promised Cost Check',
        default=True,
        help='Show optional vendor promised cost comparison columns.',
    )
    show_profile_detail_columns = fields.Boolean(
        string='Profile Details',
        default=False,
        help='Show optional profile-specific computed detail columns.',
    )
