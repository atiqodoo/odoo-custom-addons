# -*- coding: utf-8 -*-
"""
stock_receipt_label_wizard.py
=============================
Defines the two transient models that make up the receipt label popup:

  stock.receipt.label.wizard
  --------------------------
  Header model opened as a dialog after a purchase receipt is validated.
  Reads the done move_lines of the source pickings, aggregates them by
  (product, lot) into wizard lines, then delegates all printing to the
  standard Odoo label pipeline:

    - Product labels  → product.label.layout  (stock module inherit)
      xml_ids: stock.label_product_product (ZPL)
               product.report_product_template_label_* (PDF)

    - Lot/SN labels   → lot.label.layout
      xml_ids: stock.label_lot_template (ZPL)
               stock.action_report_lot_label (PDF / 4x12 sheet)

  By delegating to these existing wizards the module automatically
  inherits IoT Box routing: any ir.actions.report record that has
  iot.device records linked via Inventory > Configuration > Printers
  will print directly to the thermal printer over the IoT websocket.

  stock.receipt.label.wizard.line
  --------------------------------
  One row per (product, lot) combination found on the validated receipt.
  The operator can:
    • Uncheck ``selected`` to skip a product.
    • Edit ``label_qty`` to override the received quantity.

Logging
-------
Logger: ``stock_receipt_label_auto_print.wizard.stock_receipt_label_wizard``

  INFO    — wizard population summary, print action dispatched
  DEBUG   — per-line aggregation, xml_id resolution, data dict contents
  WARNING — empty selection, unsupported format fallback

Debug tip: enable logger at DEBUG level in Odoo's logging configuration::

    [handler_file]
    ...
    [logger_receipt_label]
    level=DEBUG
    handlers=file
    qualname=stock_receipt_label_auto_print
"""

import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared format selection — must stay in sync with stock_picking_type.py
# ---------------------------------------------------------------------------
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

_LOT_QTY_SELECTION = [
    ('lots',  'One label per lot / SN'),
    ('units', 'One label per unit'),
]


# ===========================================================================
# Main wizard
# ===========================================================================

class StockReceiptLabelWizard(models.TransientModel):
    """
    Interactive label-print wizard shown after a purchase receipt is validated.

    Lifecycle
    ---------
    1. ``stock.picking._build_receipt_label_wizard_action()`` calls
       ``self.env['stock.receipt.label.wizard'].create({picking_ids: ...})``
       followed by ``wizard._populate_lines()``.
    2. Odoo opens the wizard as a dialog via the returned act_window action.
    3. Operator reviews lines, adjusts ``label_qty``, then clicks
       "Print Labels" (``action_print``) or "Skip" (``action_skip``).
    4. ``action_print`` builds report actions using Odoo's existing
       product.label.layout / lot.label.layout pipeline and returns a
       ``do_multi_print`` client action.
    """

    _name = 'stock.receipt.label.wizard'
    _description = 'Receipt Label Print Wizard'

    # ------------------------------------------------------------------
    # Header fields
    # ------------------------------------------------------------------

    picking_ids = fields.Many2many(
        comodel_name='stock.picking',
        string='Receipts',
        readonly=True,
        help='The validated receipt(s) this wizard was opened for.',
    )
    picking_names = fields.Char(
        string='Receipt(s)',
        compute='_compute_picking_names',
        help='Display string of all source receipt names.',
    )
    label_scope = fields.Selection(
        selection=_SCOPE_SELECTION,
        string='Print',
        required=True,
        default='products',
        help=(
            'What to print:\n'
            '• Product Labels — uses the barcode / internal reference on the '
            'product variant.\n'
            '• Lot / SN Labels — uses the lot or serial number as the barcode '
            '(requires the Lots & Serial Numbers feature).\n'
            '• Both — prints product labels first, then lot/SN labels.'
        ),
    )
    label_format = fields.Selection(
        selection=_LABEL_FORMAT_SELECTION,
        string='Format',
        required=True,
        default='zpl',
        help=(
            'Label format to use.\n\n'
            'ZPL Labels — direct thermal output for Zebra / Bixolon printers '
            'connected via IoT Box (recommended).\n'
            '4 x 12 / 2 x 7 — PDF sheet formats for office printers.\n'
            'Dymo — for Dymo label printers.\n\n'
            'Note: Lot/SN labels only support ZPL and 4 x 12 formats; '
            'other formats fall back to 4 x 12 automatically.'
        ),
    )
    direct_windows_print = fields.Boolean(
        string='Direct Windows Print',
        help='Send ZPL directly from the Odoo Windows server to a local printer.',
    )
    windows_printer_name = fields.Char(
        string='Windows Printer',
        help='Exact Windows printer name for direct server printing.',
    )
    lot_qty_mode = fields.Selection(
        selection=_LOT_QTY_SELECTION,
        string='Lot Label Qty',
        default='lots',
        help=(
            'Applies only when printing Lot / SN labels.\n\n'
            '• One per lot/SN — prints one label per unique lot/serial number.\n'
            '• One per unit — repeats the label for each unit within the lot '
            '(useful for individual item tagging).'
        ),
    )
    wizard_line_ids = fields.One2many(
        comodel_name='stock.receipt.label.wizard.line',
        inverse_name='wizard_id',
        string='Products to Label',
    )

    # Computed helpers used by the view for conditional visibility
    has_lots = fields.Boolean(
        compute='_compute_has_lots',
        help='True when at least one received line carries a lot/serial number.',
    )
    line_count = fields.Integer(
        compute='_compute_line_count',
        help='Total number of label lines (selected + unselected).',
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends('picking_ids')
    def _compute_picking_names(self):
        for rec in self:
            rec.picking_names = ', '.join(rec.picking_ids.mapped('name')) or '—'

    @api.depends('wizard_line_ids.lot_id')
    def _compute_has_lots(self):
        for rec in self:
            rec.has_lots = bool(rec.wizard_line_ids.filtered('lot_id'))

    @api.depends('wizard_line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.wizard_line_ids)

    # ------------------------------------------------------------------
    # Wizard population
    # ------------------------------------------------------------------

    def _populate_lines(self):
        """
        Reads the done move_lines of all pickings in ``self.picking_ids``
        and creates one ``stock.receipt.label.wizard.line`` per unique
        (product_id, lot_id) pair.

        Aggregation logic
        -----------------
        • Skips move_lines where quantity (done qty in Odoo 18) is zero
          or rounds to zero against the line's UoM rounding.
        • Groups by (product_id, lot_id).  Lines with no lot share a
          single wizard line per product.
        • The default ``label_qty`` is set to ``max(1, int(qty_done))``.

        Side effects
        ------------
        • Sets ``label_scope`` to 'both' when any lot lines are found and
          the picking type default scope is 'products'.
        • Inherits ``label_format`` from the first picking's operation type
          if ``receipt_label_format`` is configured there.

        Logging
        -------
        DEBUG lines show every move_line inclusion / skip decision.
        INFO  line summarises total lines created.
        """
        self.ensure_one()

        _logger.debug(
            '[_populate_lines] wizard=%d  pickings=%s',
            self.id,
            ', '.join(self.picking_ids.mapped('name')),
        )

        # aggregated[key] = {'qty': float, 'move_line_ids': [int, ...]}
        aggregated = defaultdict(lambda: {'qty': 0.0, 'move_line_ids': []})

        for picking in self.picking_ids:
            for ml in picking.move_line_ids:
                rounding = ml.product_uom_id.rounding or 0.001

                if float_is_zero(ml.quantity, precision_rounding=rounding):
                    _logger.debug(
                        '[_populate_lines] SKIP move_line id=%d '
                        'product="%s"  qty_done=%.4f (rounds to zero)',
                        ml.id,
                        ml.product_id.display_name,
                        ml.quantity,
                    )
                    continue

                key = (ml.product_id.id, ml.lot_id.id if ml.lot_id else 0)
                aggregated[key]['qty'] += ml.quantity
                aggregated[key]['move_line_ids'].append(ml.id)

                _logger.debug(
                    '[_populate_lines] INCLUDE move_line id=%d '
                    'product="%s"  lot="%s"  qty=%.4f  running_total=%.4f',
                    ml.id,
                    ml.product_id.display_name,
                    ml.lot_id.name if ml.lot_id else 'None',
                    ml.quantity,
                    aggregated[key]['qty'],
                )

        if not aggregated:
            _logger.warning(
                '[_populate_lines] wizard=%d — no done quantities found in %s. '
                'No lines will be created.',
                self.id,
                ', '.join(self.picking_ids.mapped('name')),
            )
            return

        # Sort by product display_name for a consistent operator experience
        sorted_keys = sorted(
            aggregated.keys(),
            key=lambda k: self.env['product.product'].browse(k[0]).display_name,
        )

        line_vals_list = []
        for key in sorted_keys:
            product_id, lot_id = key
            data = aggregated[key]
            qty_done = data['qty']
            label_qty = max(1, int(qty_done))

            line_vals_list.append({
                'wizard_id':      self.id,
                'product_id':     product_id,
                'lot_id':         lot_id or False,
                'move_line_ids':  [(6, 0, data['move_line_ids'])],
                'qty_received':   qty_done,
                'label_qty':      label_qty,
                'selected':       True,
            })

            _logger.debug(
                '[_populate_lines] line: product_id=%d  lot_id=%s  '
                'qty_received=%.4f  label_qty=%d',
                product_id,
                lot_id or 'None',
                qty_done,
                label_qty,
            )

        self.env['stock.receipt.label.wizard.line'].create(line_vals_list)

        _logger.info(
            '[_populate_lines] wizard=%d  lines_created=%d  pickings=%s',
            self.id,
            len(line_vals_list),
            ', '.join(self.picking_ids.mapped('name')),
        )

        # ---- Auto-adjust scope and format --------------------------------

        # If any lot lines exist and the default scope is product-only,
        # switch to 'both' so operators don't miss lot labels.
        has_lots = any(k[1] for k in sorted_keys)
        if has_lots and self.label_scope == 'products':
            _logger.debug(
                '[_populate_lines] lot lines detected → auto-setting '
                'label_scope to "both"',
            )
            self.label_scope = 'both'

        # Inherit label format from operation type if configured
        if self.picking_ids:
            pt = self.picking_ids[0].picking_type_id
            if pt.receipt_label_format:
                _logger.debug(
                    '[_populate_lines] inheriting label_format="%s" from '
                    'picking type "%s"',
                    pt.receipt_label_format,
                    pt.name,
                )
                self.label_format = pt.receipt_label_format
            if pt.receipt_label_scope:
                if not (has_lots and self.label_scope == 'both'):
                    self.label_scope = pt.receipt_label_scope
            self.direct_windows_print = pt.receipt_direct_windows_print
            self.windows_printer_name = pt.receipt_windows_printer_name

    # ------------------------------------------------------------------
    # Print action — main entry point
    # ------------------------------------------------------------------

    def action_print(self):
        """
        Main button action: builds label report actions and returns a
        ``do_multi_print`` client action so Odoo's frontend routes them
        to the correct printer (IoT Box or browser download).

        Flow
        ----
        1. Validate that at least one line is selected.
        2. Build product-label actions if scope includes 'products'.
        3. Build lot-label actions if scope includes 'lots' and lot lines exist.
        4. Return ``do_multi_print`` with all actions, or raise if none generated.

        Raises
        ------
        UserError
            If no lines are selected, or no report actions could be generated.
        """
        self.ensure_one()

        selected = self.wizard_line_ids.filtered('selected')

        _logger.info(
            '[action_print] wizard=%d  scope=%s  format=%s  '
            'selected_lines=%d / total_lines=%d',
            self.id,
            self.label_scope,
            self.label_format,
            len(selected),
            len(self.wizard_line_ids),
        )

        if not selected:
            raise UserError(_(
                'No products selected. '
                'Please tick at least one product line before printing.'
            ))

        if self.direct_windows_print:
            return self._action_print_direct_windows(selected)

        report_actions = []

        # ---- Product labels -------------------------------------------
        if self.label_scope in ('products', 'both'):
            _logger.debug('[action_print] building product label actions')
            product_actions = self._build_product_label_actions(selected)
            report_actions.extend(product_actions)
            _logger.info(
                '[action_print] product label actions built: count=%d',
                len(product_actions),
            )

        # ---- Lot / SN labels -----------------------------------------
        if self.label_scope in ('lots', 'both'):
            lot_lines = selected.filtered('lot_id')
            if lot_lines:
                _logger.debug(
                    '[action_print] building lot label actions for %d lot lines',
                    len(lot_lines),
                )
                lot_actions = self._build_lot_label_actions(lot_lines)
                report_actions.extend(lot_actions)
                _logger.info(
                    '[action_print] lot label actions built: count=%d',
                    len(lot_actions),
                )
            else:
                if self.label_scope == 'lots':
                    raise UserError(_(
                        'No lot/serial number lines are selected. '
                        'Switch the print scope to "Product Labels" or '
                        'select lines that carry a lot/SN.'
                    ))
                _logger.debug(
                    '[action_print] scope=both but no lot lines selected — '
                    'skipping lot label step',
                )

        if not report_actions:
            _logger.warning(
                '[action_print] wizard=%d — no report actions were generated. '
                'Possible causes: label_qty is 0 on all lines, or an '
                'unsupported format was selected.',
                self.id,
            )
            raise UserError(_(
                'No labels could be generated. '
                'Check that selected lines have a label quantity > 0 and '
                'that the chosen format is supported.'
            ))

        _logger.info(
            '[action_print] returning do_multi_print with %d report action(s)',
            len(report_actions),
        )

        return {
            'type': 'ir.actions.client',
            'tag':  'do_multi_print',
            'params': {
                'reports':       report_actions,
                'anotherAction': False,
            },
        }

    # ------------------------------------------------------------------
    # Skip / utility actions
    # ------------------------------------------------------------------

    def action_skip(self):
        """Close the wizard without printing."""
        _logger.info('[action_skip] wizard=%d — operator skipped label printing', self.id)
        return {'type': 'ir.actions.act_window_close'}

    def action_select_all(self):
        """Tick all wizard lines."""
        _logger.debug('[action_select_all] wizard=%d', self.id)
        self.wizard_line_ids.write({'selected': True})
        return self._reload_action()

    def action_deselect_all(self):
        """Untick all wizard lines."""
        _logger.debug('[action_deselect_all] wizard=%d', self.id)
        self.wizard_line_ids.write({'selected': False})
        return self._reload_action()

    def _reload_action(self):
        """Return an act_window that reopens the current wizard dialog."""
        return {
            'type':      'ir.actions.act_window',
            'name':      _('Print Receipt Labels'),
            'res_model': self._name,
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }

    # ------------------------------------------------------------------
    # Direct Windows print path
    # ------------------------------------------------------------------

    def _action_print_direct_windows(self, selected_lines):
        """Render ZPL and send it directly to a local Windows printer."""
        self.ensure_one()

        if 'zpl' not in (self.label_format or ''):
            raise UserError(_(
                'Direct Windows printing only supports ZPL labels. '
                'Set the label format to "ZPL Labels".'
            ))

        printer_name = (self.windows_printer_name or '').strip()
        if not printer_name:
            raise UserError(_(
                'No Windows printer name is configured on this receipt '
                'operation type.'
            ))

        zpl_chunks = []

        if self.label_scope in ('products', 'both'):
            zpl_chunks.append(self._render_product_label_zpl(selected_lines))

        if self.label_scope in ('lots', 'both'):
            lot_lines = selected_lines.filtered('lot_id')
            if lot_lines:
                zpl_chunks.append(self._render_lot_label_zpl(lot_lines))
            elif self.label_scope == 'lots':
                raise UserError(_(
                    'No lot/serial number lines are selected. '
                    'Switch the print scope to "Product Labels" or '
                    'select lines that carry a lot/SN.'
                ))

        zpl_data = ''.join(chunk for chunk in zpl_chunks if chunk)
        if not zpl_data.strip():
            raise UserError(_('No ZPL labels could be generated.'))

        self._send_raw_to_windows_printer(printer_name, zpl_data)

        _logger.info(
            '[direct_windows_print] wizard=%d printer="%s" bytes=%d',
            self.id,
            printer_name,
            len(zpl_data.encode('utf-8')),
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('Labels sent to %(printer)s', printer=printer_name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _render_product_label_zpl(self, selected_lines):
        """Render compact 27mm x 27mm product labels, two stickers per row."""
        labels = []
        for line in selected_lines:
            qty = int(line.label_qty)
            if qty <= 0:
                continue

            barcode = line.lot_id.name if line.lot_id else line.product_barcode
            for _index in range(qty):
                labels.append({
                    'title': self.env.company.name or '',
                    'name': line.product_id.display_name,
                    'barcode': barcode,
                })

        return self._build_27mm_two_column_zpl(labels)

    def _render_lot_label_zpl(self, lot_lines):
        """Render compact 27mm x 27mm lot labels, two stickers per row."""
        labels = []
        if self.lot_qty_mode == 'lots':
            for line in lot_lines:
                labels.append({
                    'title': self.env.company.name or '',
                    'name': line.product_id.display_name,
                    'barcode': line.lot_id.name,
                })
        else:
            for line in lot_lines:
                qty = max(1, int(line.label_qty))
                for _index in range(qty):
                    labels.append({
                        'title': self.env.company.name or '',
                        'name': line.product_id.display_name,
                        'barcode': line.lot_id.name,
                    })

        return self._build_27mm_two_column_zpl(labels)

    def _build_27mm_two_column_zpl(self, labels):
        """Return ZPL rows for 2-up 27mm x 27mm labels on 203 dpi media."""
        config = self.env['barcode.label.config'].get_default_config()
        if config.printer_language == 'epl':
            return self._build_27mm_two_column_epl(labels, config)
        rows = []
        for index in range(0, len(labels), 2):
            left = labels[index]
            right = labels[index + 1] if index + 1 < len(labels) else None
            rows.append(
                '^XA\n'
                '^CI28\n'
                '^MD%d\n'
                '^PR%d\n'
                '^PW%d\n'
                '^LL%d\n'
                '^LH0,0\n'
                '%s'
                '%s'
                '^XZ\n'
                % (
                    config.darkness,
                    config.print_speed,
                    config.print_width,
                    config.label_length,
                    self._build_27mm_zpl_panel(left, x_offset=config.left_x, config=config),
                    self._build_27mm_zpl_panel(right, x_offset=config.right_x, config=config) if right else '',
                )
            )
        return ''.join(rows)

    def _build_27mm_two_column_epl(self, labels, config):
        rows = []
        for index in range(0, len(labels), 2):
            left = labels[index]
            right = labels[index + 1] if index + 1 < len(labels) else None
            rows.append(
                'N\n'
                'q%d\n'
                'Q%d,24\n'
                'D%d\n'
                'S%d\n'
                '%s'
                '%s'
                'P1\n'
                % (
                    config.print_width,
                    config.label_length,
                    self._epl_darkness(config),
                    max(1, int(config.print_speed)),
                    self._build_27mm_epl_panel(left, x_offset=config.left_x, config=config),
                    self._build_27mm_epl_panel(right, x_offset=config.right_x, config=config) if right else '',
                )
            )
        return ''.join(rows)

    def _build_27mm_epl_panel(self, label, x_offset, config):
        barcode = self._clean_epl_text(label.get('barcode') or '')
        title = self._clean_epl_text(label.get('title') or 'Mzaramo Paints')[:config.title_max_chars]
        name_lines = self._wrap_label_text(
            label.get('name') or '',
            line_length=config.text_line_chars,
            max_lines=config.text_max_lines,
        )
        line_1 = self._clean_epl_text(name_lines[0] if name_lines else '')
        line_2 = self._clean_epl_text(name_lines[1] if len(name_lines) > 1 else '')
        barcode_width = self._fit_barcode_width(barcode, max(1, int(config.barcode_module_width)), config)
        barcode_x = self._barcode_x_offset(x_offset, barcode, barcode_width, config)
        barcode_type = '3' if config.barcode_type == 'code39' else '1'
        wide_width = max(barcode_width + 1, barcode_width * max(2, int(config.barcode_wide_ratio)))
        return (
            'A%d,%d,0,3,1,1,N,"%s"\n'
            'A%d,%d,0,2,1,1,N,"%s"\n'
            'A%d,%d,0,2,1,1,N,"%s"\n'
            'B%d,%d,0,%s,%d,%d,%d,B,"%s"\n'
        ) % (
            x_offset,
            config.title_y,
            title,
            x_offset,
            config.line_1_y,
            line_1,
            x_offset,
            config.line_2_y,
            line_2,
            barcode_x,
            config.barcode_y,
            barcode_type,
            barcode_width,
            wide_width,
            config.barcode_height,
            barcode,
        )

    def _build_27mm_zpl_panel(self, label, x_offset, config):
        """Return one 27mm sticker panel inside a 2-up ZPL row."""
        barcode = self._clean_zpl_text(label.get('barcode') or '')
        title = self._clean_zpl_text(label.get('title') or 'Mzaramo Paints')
        name_lines = self._wrap_label_text(
            label.get('name') or '',
            line_length=config.text_line_chars,
            max_lines=config.text_max_lines,
        )

        title = title[:config.title_max_chars]
        line_1 = name_lines[0] if name_lines else ''
        line_2 = name_lines[1] if len(name_lines) > 1 else ''
        barcode_width = self._fit_barcode_width(barcode, max(1, int(config.barcode_module_width)), config)
        barcode_x = self._barcode_x_offset(x_offset, barcode, barcode_width, config)

        return (
            '^FO%d,%d^A0N,%d,%d^FD%s^FS\n'
            '^FO%d,%d^A0N,%d,%d^FD%s^FS\n'
            '^FO%d,%d^A0N,%d,%d^FD%s^FS\n'
            '%s'
        ) % (
            x_offset,
            config.title_y,
            config.title_font_height,
            config.title_font_width,
            self._zpl_field(title),
            x_offset,
            config.line_1_y,
            config.text_font_height,
            config.text_font_width,
            self._zpl_field(line_1),
            x_offset,
            config.line_2_y,
            config.text_font_height,
            config.text_font_width,
            self._zpl_field(line_2),
            self._build_barcode_command(barcode_x, barcode_width, barcode, config),
        )

    def _barcode_x_offset(self, x_offset, barcode, module_width, config):
        """Estimate Code128 width and center it inside a 27mm panel."""
        if not config.center_barcode:
            return x_offset
        clean = self._clean_zpl_text(barcode)
        encoded_chars = len(clean)
        estimated_width = self._estimate_barcode_width(encoded_chars, module_width, config)
        usable_width = max(1, int(config.panel_width))
        margin = max(2, int((usable_width - estimated_width) / 2))
        return x_offset + margin

    def _fit_barcode_width(self, barcode, preferred_width, config):
        if not config.auto_fit_barcode:
            return max(1, int(preferred_width))
        clean = self._clean_zpl_text(barcode)
        module_width = max(1, int(preferred_width))
        panel_width = max(1, int(config.panel_width))
        while module_width > 1:
            estimated_width = self._estimate_barcode_width(len(clean), module_width, config)
            if estimated_width <= panel_width:
                break
            module_width -= 1
        return module_width

    def _estimate_barcode_width(self, char_count, module_width, config):
        if config.barcode_type == 'code39':
            return module_width * (char_count * 16 + 35)
        return module_width * ((char_count + 3) * 11 + 13)

    def _build_barcode_command(self, x_offset, module_width, barcode, config):
        if config.barcode_type == 'code39':
            return '^FO%d,%d^BY%d,%d,%d^B3N,N,%d,Y,N^FD%s^FS\n' % (
                x_offset,
                config.barcode_y,
                module_width,
                config.barcode_wide_ratio,
                config.barcode_height,
                config.barcode_height,
                self._zpl_field(barcode),
            )
        return '^FO%d,%d^BY%d,%d,%d^BCN,%d,Y,N,N^FD%s^FS\n' % (
            x_offset,
            config.barcode_y,
            module_width,
            config.barcode_wide_ratio,
            config.barcode_height,
            config.barcode_height,
            self._zpl_field(barcode),
        )

    def _wrap_label_text(self, text, line_length=18, max_lines=2):
        """Wrap product text into short printer-friendly lines."""
        clean = self._clean_zpl_text(text)
        words = clean.split()
        lines = []
        current = ''

        for word in words:
            candidate = (current + ' ' + word).strip()
            if len(candidate) <= line_length:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word[:line_length]
            if len(lines) >= max_lines:
                break

        if current and len(lines) < max_lines:
            lines.append(current)

        return lines[:max_lines]

    def _clean_zpl_text(self, value):
        """Keep label text printable and remove ZPL control characters."""
        value = str(value or '')
        for char in ('^', '~', '\r', '\n', '\t'):
            value = value.replace(char, ' ')
        return ' '.join(value.split())

    def _zpl_field(self, value):
        """Escape backslashes for ZPL field data."""
        return self._clean_zpl_text(value).replace('\\', '\\\\')

    def _clean_epl_text(self, value):
        return self._clean_zpl_text(value).replace('"', "'")

    def _epl_darkness(self, config):
        return min(15, max(0, int(config.darkness)))

    def _send_raw_to_windows_printer(self, printer_name, payload):
        """Send raw ZPL text to a Windows printer through the local spooler."""
        try:
            import win32print
        except ImportError as exc:
            raise UserError(_(
                'Direct Windows printing requires pywin32 in the Python used '
                'by the Odoo service.'
            )) from exc

        payload_bytes = payload.encode('utf-8') if isinstance(payload, str) else payload
        handle = None
        try:
            handle = win32print.OpenPrinter(printer_name)
            job = win32print.StartDocPrinter(
                handle,
                1,
                ('Odoo ZPL Labels', None, 'RAW'),
            )
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, payload_bytes)
                win32print.EndPagePrinter(handle)
            finally:
                win32print.EndDocPrinter(handle)
            return job
        except Exception as exc:
            _logger.error(
                '[direct_windows_print] failed printer="%s": %s',
                printer_name,
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Could not print to Windows printer "%(printer)s": %(err)s',
                printer=printer_name,
                err=str(exc),
            ))
        finally:
            if handle:
                win32print.ClosePrinter(handle)

    # ------------------------------------------------------------------
    # Product label builder
    # ------------------------------------------------------------------

    def _prepare_product_label_data(self, selected_lines):
        """Build the data dict consumed by Odoo's product ZPL report."""
        quantity_by_product = {}
        custom_barcodes = defaultdict(list)
        all_product_ids = []

        for line in selected_lines:
            pid = line.product_id.id
            qty = int(line.label_qty)

            if qty <= 0:
                _logger.debug(
                    '[_prepare_product_label_data] SKIP product="%s" '
                    'label_qty=%d (must be > 0)',
                    line.product_id.display_name,
                    qty,
                )
                continue

            all_product_ids.append(pid)

            if line.lot_id:
                custom_barcodes[pid].append((line.lot_id.name, qty))
            else:
                quantity_by_product[pid] = quantity_by_product.get(pid, 0) + qty

        if not quantity_by_product and not custom_barcodes:
            _logger.warning(
                '[_prepare_product_label_data] nothing to print - '
                'all selected lines have label_qty <= 0',
            )
            return {}

        try:
            layout_wizard = self.env['product.label.layout'].create({
                'product_ids':    [(6, 0, list(set(all_product_ids)))],
                'print_format':   self.label_format,
                'custom_quantity': 1,
                'move_quantity':  'custom',
            })
        except Exception as exc:
            _logger.error(
                '[_prepare_product_label_data] failed to create '
                'product.label.layout: %s',
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Could not initialise label layout wizard: %(err)s',
                err=str(exc),
            ))

        return {
            'active_model':        'product.product',
            'quantity_by_product': quantity_by_product,
            'custom_barcodes':     dict(custom_barcodes),
            'layout_wizard':       layout_wizard.id,
            'price_included':      'xprice' in self.label_format,
        }

    def _build_product_label_actions(self, selected_lines):
        """
        Builds a product label report action for the given wizard lines.

        Uses Odoo's existing ``stock.label_product_product`` (ZPL) or
        ``product.report_product_template_label_*`` (PDF) reports directly,
        bypassing ``product.label.layout.process()`` so we can inject our
        custom per-line ``label_qty`` values instead of the raw done
        quantities from the move_lines.

        Data dict format (consumed by report.stock.label_product_product_view)
        -----------------------------------------------------------------------
        ``quantity_by_product`` : {product_id (int): label_qty (int)}
            For products without a lot.
        ``custom_barcodes``     : {product_id (int): [(lot_name, qty), ...]}
            For lot-tracked products; the lot_name is used as the barcode
            value so the label shows the lot barcode, not the product EAN.
        ``layout_wizard``       : int (product.label.layout record id)
            Needed by _get_report_values for pricelist lookup.
        ``price_included``      : bool
            Set True for '*xprice' formats so the ZPL/PDF template renders
            the price block.
        ``active_model``        : 'product.product'
            Required discriminator in _get_report_values.

        Parameters
        ----------
        selected_lines : stock.receipt.label.wizard.line recordset
            Already-filtered to only selected lines.

        Returns
        -------
        list[dict]
            A list containing one report action dict, or empty list on error.
        """
        _logger.debug(
            '[_build_product_label_actions] format=%s  lines=%d',
            self.label_format,
            len(selected_lines),
        )

        quantity_by_product = {}  # {product_id: int_qty}
        custom_barcodes = defaultdict(list)  # {product_id: [(lot_name, int_qty)]}
        all_product_ids = []

        for line in selected_lines:
            pid = line.product_id.id
            qty = int(line.label_qty)

            if qty <= 0:
                _logger.debug(
                    '[_build_product_label_actions] SKIP product="%s" '
                    'label_qty=%d (must be > 0)',
                    line.product_id.display_name,
                    qty,
                )
                continue

            all_product_ids.append(pid)

            if line.lot_id:
                # Lot-tracked: use lot name as the barcode value so the
                # printed barcode scans to the lot, not the product EAN.
                custom_barcodes[pid].append((line.lot_id.name, qty))
                _logger.debug(
                    '[_build_product_label_actions] custom_barcodes  '
                    'product="%s"  lot="%s"  qty=%d',
                    line.product_id.display_name,
                    line.lot_id.name,
                    qty,
                )
            else:
                quantity_by_product[pid] = quantity_by_product.get(pid, 0) + qty
                _logger.debug(
                    '[_build_product_label_actions] quantity_by_product  '
                    'product="%s"  qty=%d  running=%d',
                    line.product_id.display_name,
                    qty,
                    quantity_by_product[pid],
                )

        if not quantity_by_product and not custom_barcodes:
            _logger.warning(
                '[_build_product_label_actions] nothing to print — '
                'all selected lines have label_qty <= 0',
            )
            return []

        # Create a minimal product.label.layout record so _get_report_values
        # can look up the pricelist (required for '*xprice' formats).
        unique_pids = list(set(all_product_ids))
        try:
            layout_wizard = self.env['product.label.layout'].create({
                'product_ids':    [(6, 0, unique_pids)],
                'print_format':   self.label_format,
                'custom_quantity': 1,
                'move_quantity':  'custom',
            })
            _logger.debug(
                '[_build_product_label_actions] layout_wizard id=%d created',
                layout_wizard.id,
            )
        except Exception as exc:
            _logger.error(
                '[_build_product_label_actions] failed to create '
                'product.label.layout: %s',
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Could not initialise label layout wizard: %(err)s',
                err=str(exc),
            ))

        xml_id = self._get_product_label_xml_id()
        if not xml_id:
            _logger.warning(
                '[_build_product_label_actions] unknown format "%s" — '
                'falling back to ZPL',
                self.label_format,
            )
            xml_id = 'stock.label_product_product'

        data = {
            'active_model':        'product.product',
            'quantity_by_product': quantity_by_product,
            'custom_barcodes':     dict(custom_barcodes),
            'layout_wizard':       layout_wizard.id,
            'price_included':      'xprice' in self.label_format,
        }

        _logger.debug(
            '[_build_product_label_actions] xml_id=%s  '
            'qty_by_product=%s  custom_barcodes_keys=%s',
            xml_id,
            quantity_by_product,
            list(custom_barcodes.keys()),
        )

        try:
            report_ref = self.env.ref(xml_id)
        except ValueError as exc:
            _logger.error(
                '[_build_product_label_actions] env.ref("%s") failed: %s',
                xml_id,
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Label report "%(xml_id)s" not found. '
                'Ensure the stock module is installed.',
                xml_id=xml_id,
            ))

        try:
            # Pass None as res_ids: _get_report_values ignores docids and
            # builds its output entirely from the data dict (same pattern
            # used by product.label.layout.process()).
            action = report_ref.report_action(None, data=data, config=False)
            action.update({'close_on_report_download': True})
            _logger.debug(
                '[_build_product_label_actions] report_action built: %s',
                action.get('name'),
            )
            return [action]
        except Exception as exc:
            _logger.error(
                '[_build_product_label_actions] report_action() raised: %s',
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Failed to generate product label report: %(err)s',
                err=str(exc),
            ))

    def _get_product_label_xml_id(self):
        """
        Maps ``self.label_format`` to the correct ``ir.actions.report`` XML ID.

        Replicates the logic from ``product.label.layout._prepare_report_data``
        (base) and the stock module's ``_prepare_report_data`` override so the
        same reports are used regardless of whether the standard wizard or our
        wizard triggers them.

        Format → XML ID mapping
        -----------------------
        zpl / zplxprice   → stock.label_product_product      (qweb-text / ZPL)
        dymo              → product.report_product_template_label_dymo
        NxMxprice         → product.report_product_template_label_NxM
        NxM  (no price)   → product.report_product_template_label_NxM_noprice

        Returns
        -------
        str  — the XML ID, or '' if the format cannot be mapped.
        """
        fmt = self.label_format or ''

        if 'zpl' in fmt:
            xml_id = 'stock.label_product_product'
            _logger.debug('[_get_product_label_xml_id] %s → %s', fmt, xml_id)
            return xml_id

        if fmt == 'dymo':
            xml_id = 'product.report_product_template_label_dymo'
            _logger.debug('[_get_product_label_xml_id] %s → %s', fmt, xml_id)
            return xml_id

        # NxM and NxMxprice formats
        if 'x' in fmt:
            parts = fmt.split('x')
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                cols, rows = parts[0], parts[1]
                xml_id = 'product.report_product_template_label_%sx%s' % (cols, rows)
                if 'xprice' not in fmt:
                    xml_id += '_noprice'
                _logger.debug('[_get_product_label_xml_id] %s → %s', fmt, xml_id)
                return xml_id

        _logger.warning(
            '[_get_product_label_xml_id] cannot map format "%s" to an xml_id',
            fmt,
        )
        return ''

    # ------------------------------------------------------------------
    # Lot label builder
    # ------------------------------------------------------------------

    def _build_lot_label_actions(self, lot_lines):
        """
        Builds a lot/SN label report action by creating a ``lot.label.layout``
        wizard and calling its ``process()`` method.

        When ``lot_qty_mode == 'units'`` and the operator has customised
        ``label_qty`` on a line, we honour the custom qty by constructing
        the docids list manually (repeating the lot_id ``label_qty`` times)
        instead of reading from move_line quantities.

        When ``lot_qty_mode == 'lots'`` each lot prints exactly one label
        regardless of ``label_qty``.

        Print format mapping
        --------------------
        Lot labels only support 'zpl' and '4x12':
          label_format contains 'zpl'  → lot print_format = 'zpl'
          anything else                → lot print_format = '4x12'

        Parameters
        ----------
        lot_lines : stock.receipt.label.wizard.line recordset
            Lines that carry a lot_id and are selected.

        Returns
        -------
        list[dict]  — list containing the report action, or empty list.
        """
        _logger.debug(
            '[_build_lot_label_actions] lot_qty_mode=%s  lot_lines=%d',
            self.lot_qty_mode,
            len(lot_lines),
        )

        # lot.label.layout only supports 'zpl' and '4x12'
        lot_format = 'zpl' if 'zpl' in self.label_format else '4x12'
        _logger.debug(
            '[_build_lot_label_actions] label_format=%s → lot_format=%s',
            self.label_format,
            lot_format,
        )

        if self.lot_qty_mode == 'lots':
            # Standard 'one per lot' flow — delegate entirely to lot.label.layout
            move_line_ids = lot_lines.mapped('move_line_ids')
            _logger.debug(
                '[_build_lot_label_actions] mode=lots  move_lines=%d',
                len(move_line_ids),
            )
            try:
                wizard = self.env['lot.label.layout'].create({
                    'move_line_ids': [(6, 0, move_line_ids.ids)],
                    'label_quantity': 'lots',
                    'print_format':   lot_format,
                })
                action = wizard.process()
                if action:
                    action.update({'close_on_report_download': True})
                    return [action]
                return []
            except Exception as exc:
                _logger.error(
                    '[_build_lot_label_actions] lot.label.layout.process() '
                    'raised: %s',
                    exc,
                    exc_info=True,
                )
                raise UserError(_(
                    'Failed to generate lot label report: %(err)s',
                    err=str(exc),
                ))

        # mode == 'units': build docids manually to honour custom label_qty
        # lot.label.layout in 'units' mode repeats lot_id N times in docids
        # where N = int(qty_done).  We substitute our label_qty instead.
        docids = []
        for line in lot_lines:
            qty = max(1, int(line.label_qty))
            docids.extend([line.lot_id.id] * qty)
            _logger.debug(
                '[_build_lot_label_actions] lot="%s"  label_qty=%d  '
                'docids_added=%d',
                line.lot_id.name,
                qty,
                qty,
            )

        if not docids:
            _logger.warning(
                '[_build_lot_label_actions] mode=units — no docids built '
                '(label_qty <= 0 on all lot lines)',
            )
            return []

        xml_id = (
            'stock.label_lot_template'
            if lot_format == 'zpl'
            else 'stock.action_report_lot_label'
        )

        _logger.debug(
            '[_build_lot_label_actions] mode=units  xml_id=%s  '
            'docids_count=%d',
            xml_id,
            len(docids),
        )

        try:
            report_ref = self.env.ref(xml_id)
            action = report_ref.report_action(docids, config=False)
            action.update({'close_on_report_download': True})
            return [action]
        except Exception as exc:
            _logger.error(
                '[_build_lot_label_actions] report_action() raised: %s',
                exc,
                exc_info=True,
            )
            raise UserError(_(
                'Failed to generate lot label report: %(err)s',
                err=str(exc),
            ))


# ===========================================================================
# Wizard line
# ===========================================================================

class StockReceiptLabelWizardLine(models.TransientModel):
    """
    One row in the receipt label popup representing a single
    (product, lot) combination found on the validated receipt.

    Fields
    ------
    wizard_id     : parent wizard
    product_id    : the received product variant
    lot_id        : lot or serial number (empty for untracked products)
    move_line_ids : source move_lines used to compute qty_received
    qty_received  : total done quantity (readonly, from move_lines)
    label_qty     : operator-editable number of labels to print
    selected      : when False the line is skipped during printing
    product_barcode : computed — EAN13 if set, otherwise internal reference
    uom_name       : computed — short UoM name for display
    """

    _name = 'stock.receipt.label.wizard.line'
    _description = 'Receipt Label Wizard Line'
    _order = 'product_id, lot_id'

    # ------------------------------------------------------------------
    # Relational fields
    # ------------------------------------------------------------------

    wizard_id = fields.Many2one(
        comodel_name='stock.receipt.label.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        required=True,
        readonly=True,
    )
    lot_id = fields.Many2one(
        comodel_name='stock.lot',
        string='Lot / SN',
        readonly=True,
    )
    move_line_ids = fields.Many2many(
        comodel_name='stock.move.line',
        string='Source Move Lines',
        readonly=True,
        help='The validated move lines that contributed to qty_received.',
    )

    # ------------------------------------------------------------------
    # Quantity fields
    # ------------------------------------------------------------------

    qty_received = fields.Float(
        string='Received',
        digits='Product Unit of Measure',
        readonly=True,
        help='Total quantity actually received (sum of done move_line quantities).',
    )
    label_qty = fields.Integer(
        string='Labels',
        default=1,
        help='How many labels to print for this product / lot.',
    )

    # ------------------------------------------------------------------
    # Selection / display fields
    # ------------------------------------------------------------------

    selected = fields.Boolean(
        string='Print',
        default=True,
        help='Uncheck to exclude this line from the print job.',
    )
    product_barcode = fields.Char(
        string='Barcode',
        compute='_compute_product_barcode',
        help='EAN-13 barcode if configured, otherwise the internal reference.',
    )
    uom_name = fields.Char(
        string='Unit',
        compute='_compute_uom_name',
    )
    tracking = fields.Selection(
        related='product_id.tracking',
        readonly=True,
        help='Lot tracking type of the product (lot / serial / none).',
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends('product_id')
    def _compute_product_barcode(self):
        for line in self:
            p = line.product_id
            if p.barcode:
                line.product_barcode = p.barcode
            elif p.default_code:
                line.product_barcode = p.default_code
            else:
                line.product_barcode = str(p.id)

            _logger.debug(
                '[_compute_product_barcode] product="%s"  barcode="%s"',
                p.display_name,
                line.product_barcode,
            )

    @api.depends('product_id', 'move_line_ids')
    def _compute_uom_name(self):
        for line in self:
            if line.move_line_ids:
                line.uom_name = line.move_line_ids[0].product_uom_id.name or ''
            elif line.product_id.uom_id:
                line.uom_name = line.product_id.uom_id.name or ''
            else:
                line.uom_name = ''
