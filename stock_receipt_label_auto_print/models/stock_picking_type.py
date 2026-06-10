# -*- coding: utf-8 -*-
"""
stock_picking_type.py
=====================
Extends ``stock.picking.type`` with three fields that drive the receipt
label popup feature.  All fields are scoped to incoming operation types
but are stored on every record — the view restricts visibility.

Fields added
------------
auto_label_popup_on_receipt : Boolean
    Master switch.  When True and the operation type is for incoming
    receipts, a label-print wizard opens automatically at the end of
    every successful validation.

receipt_label_format : Selection
    Pre-selected label format in the popup wizard.  Mirrors the same
    selection as ``product_label_format`` on stock.picking.type so the
    warehouse manager picks the format once and operators never have to
    touch it.

receipt_label_scope : Selection
    Whether to print product labels, lot/SN labels, or both.  The
    wizard auto-overrides this to 'both' when it detects that any
    received product carries lot/serial tracking.

Logging
-------
Set the logger ``stock_receipt_label_auto_print.models.stock_picking_type``
to DEBUG to trace field writes.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Shared selection list — kept in sync with product.label.layout and
# stock.picking.type.product_label_format to ensure every format the
# stock module supports is also available in the popup.
_LABEL_FORMAT_SELECTION = [
    ('dymo',       'Dymo'),
    ('2x7xprice',  '2 x 7 with price'),
    ('4x7xprice',  '4 x 7 with price'),
    ('4x12',       '4 x 12'),
    ('4x12xprice', '4 x 12 with price'),
    ('zpl',        'ZPL Labels'),
    ('zplxprice',  'ZPL Labels with price'),
]

_SCOPE_SELECTION = [
    ('products', 'Product Labels'),
    ('lots',     'Lot / SN Labels'),
    ('both',     'Both'),
]


class StockPickingType(models.Model):
    """Extends stock.picking.type with receipt label popup configuration."""

    _inherit = 'stock.picking.type'

    # ------------------------------------------------------------------
    # Master switch
    # ------------------------------------------------------------------
    auto_label_popup_on_receipt = fields.Boolean(
        string='Label Popup on Receipt',
        default=False,
        help=(
            'When enabled (and the operation type is Receipts), a label '
            'printing wizard opens automatically each time a receipt is '
            'validated.  The wizard lists every product / lot that was '
            'actually received and lets the operator adjust print quantities '
            'before sending to the thermal printer.\n\n'
            'Leave disabled if you prefer the silent auto-print behaviour '
            'already built into Odoo (Auto Print Product Labels setting).'
        ),
    )

    # ------------------------------------------------------------------
    # Default label format for the popup
    # ------------------------------------------------------------------
    receipt_label_format = fields.Selection(
        selection=_LABEL_FORMAT_SELECTION,
        string='Default Label Format',
        default='zpl',
        help=(
            'Label format pre-selected in the popup wizard for this '
            'operation type.  Operators can change it per-validation inside '
            'the wizard.\n\n'
            'ZPL Labels — recommended for Bixolon / Zebra thermal printers '
            'connected via IoT Box or direct network.'
        ),
    )

    # ------------------------------------------------------------------
    # Default scope (products vs lots vs both)
    # ------------------------------------------------------------------
    receipt_label_scope = fields.Selection(
        selection=_SCOPE_SELECTION,
        string='Default Label Scope',
        default='products',
        help=(
            'Which labels to print by default.\n\n'
            '• Product Labels — one label per product variant (ignores '
            'lot/SN numbers).\n'
            '• Lot / SN Labels — one label per lot or serial number barcode '
            '(requires Lots & Serial Numbers feature).\n'
            '• Both — prints product labels and lot/SN labels in sequence.\n\n'
            'The wizard automatically switches to "Both" when it detects '
            'lot-tracked products on the receipt, regardless of this default.'
        ),
    )

    receipt_direct_windows_print = fields.Boolean(
        string='Print Directly from Windows Server',
        default=False,
        help=(
            'Send ZPL labels directly from the Odoo Windows server to a '
            'locally installed Windows printer. Use this when the label '
            'printer is connected to the server by USB/parallel cable and '
            'you are not using an IoT Box.'
        ),
    )
    receipt_windows_printer_name = fields.Char(
        string='Windows Printer Name',
        default='BIXOLON SLP-DX420 - BPL-Z',
        help=(
            'Exact Windows printer name as shown in Control Panel / '
            'Get-Printer. Example: BIXOLON SLP-DX420 - BPL-Z.'
        ),
    )
