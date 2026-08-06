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

    @api.model
    def _process_order(self, order, existing_order):
        """Backend audit/fallback for customer POS orders that should invoice."""
        partner_id = order.get('partner_id')
        to_invoice = order.get('to_invoice')
        line_count = len(order.get('lines') or [])
        _logger.info(
            "[pos_disable_invoice_download] _process_order audit | name=%s | uuid=%s | "
            "partner_id=%s | to_invoice=%s | line_count=%s | existing_order=%s",
            order.get('name'),
            order.get('uuid'),
            partner_id,
            to_invoice,
            line_count,
            bool(existing_order),
        )
        if partner_id and not to_invoice and line_count:
            _logger.warning(
                "[pos_disable_invoice_download] Backend forcing to_invoice=True because "
                "customer is selected and order is not empty | name=%s | uuid=%s | "
                "partner_id=%s | line_count=%s",
                order.get('name'),
                order.get('uuid'),
                partner_id,
                line_count,
            )
            order['to_invoice'] = True
        elif partner_id and not to_invoice:
            _logger.info(
                "[pos_disable_invoice_download] Backend invoice force skipped for empty "
                "customer order | name=%s | uuid=%s | partner_id=%s",
                order.get('name'),
                order.get('uuid'),
                partner_id,
            )
        return super()._process_order(order, existing_order)

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
