# -*- coding: utf-8 -*-

from odoo import api, fields, models
import base64
import logging

_logger = logging.getLogger(__name__)

class PosConfig(models.Model):
    _inherit = 'pos.config'
    
    allow_pdf_download = fields.Boolean('Allow PDF Download', default=True)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    pos_allow_pdf_download = fields.Boolean(related='pos_config_id.allow_pdf_download', readonly=False)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        ctx = dict(self.env.context)
        # If the POS config disables PDF download, ensure the invoice generation does not render/send PDFs
        try:
            # Some calls may be on multiple orders; if any belongs to a POS with download disabled, disable PDF generation
            if any(order.session_id and order.session_id.config_id and order.session_id.config_id.allow_pdf_download is False for order in self):
                ctx['generate_pdf'] = False
                _logger.info("POS Disable Invoice Download: generate_pdf forced to False for orders %s (config setting)", self.ids)
        except Exception:
            # Be safe: if we can't determine, defer to existing context
            pass
        return super(PosOrder, self.with_context(ctx))._generate_pos_order_invoice()

    def _add_mail_attachment(self, name, ticket, basic_ticket):
        # Re-implement core logic but skip PDF attachment when POS config disables downloads
        attachment = []
        filename = 'Receipt-' + name + '.jpg'
        receipt = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': ticket,
            'res_model': 'pos.order',
            'res_id': self.ids[0],
            'mimetype': 'image/jpeg',
        })
        attachment += [(4, receipt.id)]

        if basic_ticket:
            filename = 'Receipt-' + name + '-1' + '.jpg'
            basic_receipt = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': basic_ticket,
                'res_model': 'pos.order',
                'res_id': self.ids[0],
                'mimetype': 'image/jpeg',
            })
            attachment += [(4, basic_receipt.id)]

        # Conditionally attach invoice PDF only if allowed in POS config
        allow_pdf = True
        try:
            allow_pdf = bool(self.session_id and self.session_id.config_id and self.session_id.config_id.allow_pdf_download)
        except Exception:
            allow_pdf = True

        if allow_pdf and self.mapped('account_move'):
            _logger.info("POS Disable Invoice Download: Generating and attaching invoice PDF for order %s (allow_pdf_download=True)", self.ids)
            report = self.env['ir.actions.report']._render_qweb_pdf("account.account_invoices", self.account_move.ids[0])
            filename = name + '.pdf'
            invoice = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(report[0]),
                'res_model': 'pos.order',
                'res_id': self.ids[0],
                'mimetype': 'application/x-pdf'
            })
            attachment += [(4, invoice.id)]
        else:
            _logger.info("POS Disable Invoice Download: Skipped generating invoice PDF for order %s (allow_pdf_download=%s)", self.ids, allow_pdf)

        return attachment
