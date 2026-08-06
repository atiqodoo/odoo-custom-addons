# -*- coding: utf-8 -*-

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BarcodeLabelConfig(models.Model):
    _name = 'barcode.label.config'
    _description = 'Barcode Label Printer Configuration'
    _order = 'sequence, name'

    name = fields.Char(required=True, default='Bixolon 27mm 2-Up')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(string='Default')

    printer_name = fields.Char(
        string='Windows Printer',
        default='BIXOLON SLP-DX420 - BPL-Z',
        required=True,
    )
    label_title = fields.Char(
        string='Label Title',
        default=lambda self: self.env.company.name or 'Mzaramo Paints',
        required=True,
    )

    print_width = fields.Integer(string='Print Width', default=448, required=True)
    label_length = fields.Integer(string='Label Length', default=216, required=True)
    left_x = fields.Integer(string='Left Sticker X', default=8, required=True)
    right_x = fields.Integer(string='Right Sticker X', default=232, required=True)
    panel_width = fields.Integer(string='Sticker Printable Width', default=204, required=True)

    title_y = fields.Integer(string='Title Y', default=8, required=True)
    line_1_y = fields.Integer(string='Line 1 Y', default=34, required=True)
    line_2_y = fields.Integer(string='Line 2 Y', default=55, required=True)
    barcode_y = fields.Integer(string='Barcode Y', default=86, required=True)
    barcode_height = fields.Integer(string='Barcode Height', default=58, required=True)

    title_font_height = fields.Integer(string='Title Font Height', default=22, required=True)
    title_font_width = fields.Integer(string='Title Font Width', default=18, required=True)
    text_font_height = fields.Integer(string='Text Font Height', default=18, required=True)
    text_font_width = fields.Integer(string='Text Font Width', default=15, required=True)
    title_max_chars = fields.Integer(string='Title Max Characters', default=17, required=True)
    text_line_chars = fields.Integer(string='Product Line Characters', default=17, required=True)
    text_max_lines = fields.Integer(string='Product Lines', default=2, required=True)

    barcode_module_width = fields.Integer(string='Barcode Thickness', default=1, required=True)
    auto_fit_barcode = fields.Boolean(string='Auto Fit Barcode', default=True)
    printer_language = fields.Selection(
        selection=[
            ('zpl', 'ZPL / BPL-Z'),
            ('epl', 'EPL / BPL-E'),
        ],
        string='Printer Language',
        default='zpl',
        required=True,
    )
    barcode_type = fields.Selection(
        selection=[
            ('code39', 'Code39 - Nexx Style'),
            ('code128', 'Code128'),
        ],
        string='Barcode Type',
        default='code39',
        required=True,
    )
    barcode_wide_ratio = fields.Integer(string='Wide Bar Ratio', default=2, required=True)
    darkness = fields.Integer(string='Darkness', default=30, required=True)
    print_speed = fields.Integer(string='Print Speed', default=2, required=True)
    center_barcode = fields.Boolean(string='Center Barcode', default=True)

    @api.model
    def get_default_config(self):
        config = self.search([('is_default', '=', True)], limit=1)
        if not config:
            config = self.search([], limit=1)
        if not config:
            config = self.create({'name': _('Bixolon 27mm 2-Up'), 'is_default': True})
        return config

    def action_set_default(self):
        self.ensure_one()
        self.search([('id', '!=', self.id), ('is_default', '=', True)]).write({'is_default': False})
        self.is_default = True
        return True

    def action_test_print(self):
        self.ensure_one()
        labels = [
            {
                'title': self.label_title,
                'name': 'TEST LONG BARCODE',
                'barcode': '1081210',
            },
            {
                'title': self.label_title,
                'name': 'TEST LONGER CODE',
                'barcode': '1234567890',
            },
        ]
        payload = self._build_test_payload(labels)
        self._send_raw_to_windows_printer(payload)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('Test label sent to %(printer)s', printer=self.printer_name),
                'sticky': False,
            },
        }

    def _build_test_payload(self, labels):
        if self.printer_language == 'epl':
            return self._build_test_epl(labels)
        return self._build_test_zpl(labels)

    def _build_test_zpl(self, labels):
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
                    self.darkness,
                    self.print_speed,
                    self.print_width,
                    self.label_length,
                    self._build_test_panel(left, self.left_x),
                    self._build_test_panel(right, self.right_x) if right else '',
                )
            )
        return ''.join(rows)

    def _build_test_panel(self, label, x_offset):
        barcode = self._clean_zpl_text(label.get('barcode') or '')
        title = self._clean_zpl_text(label.get('title') or '')[:self.title_max_chars]
        name = self._clean_zpl_text(label.get('name') or '')[:self.text_line_chars]
        module_width = max(1, int(self.barcode_module_width))
        module_width = self._fit_barcode_width(barcode, module_width)
        barcode_x = self._barcode_x_offset(x_offset, barcode, module_width)
        return (
            '^FO%d,%d^A0N,%d,%d^FD%s^FS\n'
            '^FO%d,%d^A0N,%d,%d^FD%s^FS\n'
            '%s'
        ) % (
            x_offset,
            self.title_y,
            self.title_font_height,
            self.title_font_width,
            self._zpl_field(title),
            x_offset,
            self.line_1_y,
            self.text_font_height,
            self.text_font_width,
            self._zpl_field(name),
            self._build_barcode_command(barcode_x, module_width, barcode),
        )

    def _build_test_epl(self, labels):
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
                    self.print_width,
                    self.label_length,
                    self._epl_darkness(),
                    max(1, int(self.print_speed)),
                    self._build_test_epl_panel(left, self.left_x),
                    self._build_test_epl_panel(right, self.right_x) if right else '',
                )
            )
        return ''.join(rows)

    def _build_test_epl_panel(self, label, x_offset):
        barcode = self._clean_epl_text(label.get('barcode') or '')
        title = self._clean_epl_text(label.get('title') or '')[:self.title_max_chars]
        name = self._clean_epl_text(label.get('name') or '')[:self.text_line_chars]
        module_width = self._fit_barcode_width(barcode, max(1, int(self.barcode_module_width)))
        barcode_x = self._barcode_x_offset(x_offset, barcode, module_width)
        barcode_type = '3' if self.barcode_type == 'code39' else '1'
        wide_width = max(module_width + 1, module_width * max(2, int(self.barcode_wide_ratio)))
        return (
            'A%d,%d,0,3,1,1,N,"%s"\n'
            'A%d,%d,0,2,1,1,N,"%s"\n'
            'B%d,%d,0,%s,%d,%d,%d,B,"%s"\n'
        ) % (
            x_offset,
            self.title_y,
            title,
            x_offset,
            self.line_1_y,
            name,
            barcode_x,
            self.barcode_y,
            barcode_type,
            module_width,
            wide_width,
            self.barcode_height,
            barcode,
        )

    def _barcode_x_offset(self, x_offset, barcode, module_width):
        if not self.center_barcode:
            return x_offset
        clean = self._clean_zpl_text(barcode)
        estimated_width = self._estimate_barcode_width(clean, module_width)
        margin = max(2, int((max(1, self.panel_width) - estimated_width) / 2))
        return x_offset + margin

    def _fit_barcode_width(self, barcode, preferred_width):
        if not self.auto_fit_barcode:
            return max(1, int(preferred_width))
        clean = self._clean_zpl_text(barcode)
        module_width = max(1, int(preferred_width))
        panel_width = max(1, int(self.panel_width))
        while module_width > 1:
            estimated_width = self._estimate_barcode_width(clean, module_width)
            if estimated_width <= panel_width:
                break
            module_width -= 1
        return module_width

    def _estimate_barcode_width(self, clean, module_width):
        if self.barcode_type == 'code39':
            return module_width * (len(clean) * 16 + 35)
        return module_width * ((len(clean) + 3) * 11 + 13)

    def _build_barcode_command(self, x_offset, module_width, barcode):
        if self.barcode_type == 'code39':
            return '^FO%d,%d^BY%d,%d,%d^B3N,N,%d,Y,N^FD%s^FS\n' % (
                x_offset,
                self.barcode_y,
                module_width,
                self.barcode_wide_ratio,
                self.barcode_height,
                self.barcode_height,
                self._zpl_field(barcode),
            )
        return '^FO%d,%d^BY%d,%d,%d^BCN,%d,Y,N,N^FD%s^FS\n' % (
            x_offset,
            self.barcode_y,
            module_width,
            self.barcode_wide_ratio,
            self.barcode_height,
            self.barcode_height,
            self._zpl_field(barcode),
        )

    def _send_raw_to_windows_printer(self, payload):
        if not self.printer_name:
            raise UserError(_('Enter a Windows printer name.'))
        try:
            import win32print
        except ImportError as exc:
            raise UserError(_('Direct Windows printing requires pywin32.')) from exc

        payload_bytes = payload.encode('utf-8') if isinstance(payload, str) else payload
        handle = None
        try:
            handle = win32print.OpenPrinter(self.printer_name)
            win32print.StartDocPrinter(handle, 1, ('Odoo Barcode Config Test', None, 'RAW'))
            try:
                win32print.StartPagePrinter(handle)
                win32print.WritePrinter(handle, payload_bytes)
                win32print.EndPagePrinter(handle)
            finally:
                win32print.EndDocPrinter(handle)
        except Exception as exc:
            _logger.error('[barcode_label_config] test print failed printer="%s": %s', self.printer_name, exc, exc_info=True)
            raise UserError(_(
                'Could not print to Windows printer "%(printer)s": %(err)s',
                printer=self.printer_name,
                err=str(exc),
            ))
        finally:
            if handle:
                win32print.ClosePrinter(handle)

    def _clean_zpl_text(self, value):
        value = str(value or '')
        for char in ('^', '~', '\r', '\n', '\t'):
            value = value.replace(char, ' ')
        return ' '.join(value.split())

    def _zpl_field(self, value):
        return self._clean_zpl_text(value).replace('\\', '\\\\')

    def _clean_epl_text(self, value):
        value = self._clean_zpl_text(value)
        return value.replace('"', "'")

    def _epl_darkness(self):
        return min(15, max(0, int(self.darkness)))
