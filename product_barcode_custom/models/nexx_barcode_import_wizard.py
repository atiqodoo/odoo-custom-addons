import base64
import csv
import io

from odoo import api, fields, models
from odoo.exceptions import UserError


class NexxBarcodeImportWizard(models.TransientModel):
    _name = 'nexx.barcode.import.wizard'
    _description = 'Import Nexx Barcodes from CSV'

    file_data = fields.Binary('CSV File', attachment=False)
    file_name = fields.Char('File Name')
    match_by = fields.Selection([
        ('default_code', 'Internal Reference'),
        ('barcode', 'Existing (Primary) Barcode'),
        ('id', 'Product ID'),
    ], string='Match Products By', default='default_code', required=True)
    delimiter = fields.Selection([
        (',', 'Comma (,)'),
        (';', 'Semicolon (;)'),
        ('\t', 'Tab'),
    ], string='Delimiter', default=',', required=True)
    result_message = fields.Text('Result', readonly=True)
    state = fields.Selection([
        ('draft', 'Upload'),
        ('done', 'Result'),
    ], default='draft')

    def action_import(self):
        if not self.file_data:
            raise UserError("Please upload a CSV file before importing.")

        raw = base64.b64decode(self.file_data)
        try:
            content = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = raw.decode('latin-1')

        reader = csv.DictReader(io.StringIO(content), delimiter=self.delimiter)
        fieldnames = reader.fieldnames or []

        match_field = self.match_by
        if 'nexx_barcode' not in fieldnames:
            raise UserError(
                "CSV must contain a 'nexx_barcode' column.\n"
                f"Detected columns: {', '.join(fieldnames) or '(none)'}"
            )
        if match_field not in fieldnames:
            raise UserError(
                f"CSV must contain a '{match_field}' column to identify products.\n"
                f"Detected columns: {', '.join(fieldnames) or '(none)'}"
            )

        updated, skipped = 0, 0
        errors = []

        for i, row in enumerate(reader, start=2):
            identifier = (row.get(match_field) or '').strip()
            nexx_barcode = (row.get('nexx_barcode') or '').strip()

            if not identifier or not nexx_barcode:
                skipped += 1
                continue

            product = self.env['product.product'].search(
                [(match_field, '=', identifier)], limit=1
            )
            if not product:
                errors.append(f"Row {i}: no product found where {match_field} = '{identifier}'.")
                continue

            conflict = self.env['product.product'].search([
                ('nexx_barcode', '=', nexx_barcode),
                ('id', '!=', product.id),
            ], limit=1)
            if conflict:
                errors.append(
                    f"Row {i}: Nexx barcode '{nexx_barcode}' is already assigned "
                    f"to '{conflict.display_name}' (ID {conflict.id})."
                )
                continue

            product.write({'nexx_barcode': nexx_barcode})
            updated += 1

        parts = [f"Updated: {updated} product(s)."]
        if skipped:
            parts.append(f"Skipped (blank rows): {skipped}.")
        if errors:
            parts.append("Errors:\n" + "\n".join(errors))

        self.write({'result_message': "\n".join(parts), 'state': 'done'})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'nexx.barcode.import.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_download_template(self):
        # Returns a CSV template as a binary download via a URL action
        content = f"{self.match_by},nexx_barcode\n"
        csv_bytes = content.encode('utf-8')
        attachment = self.env['ir.attachment'].create({
            'name': 'nexx_barcode_import_template.csv',
            'datas': base64.b64encode(csv_bytes).decode(),
            'mimetype': 'text/csv',
            'type': 'binary',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
