# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.tools.misc import html_escape


_logger = logging.getLogger(__name__)

TALLY_LOG_HEAD = '[PNPC_TALLY]'


class VendorDocumentTallySession(models.Model):
    _name = 'vendor.document.tally.session'
    _description = 'Vendor Document Tally Session'
    _inherit = ['mail.thread']
    _order = 'write_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    source_model = fields.Selection(
        [
            ('purchase.order', 'Purchase Order'),
            ('stock.picking', 'Receipt / Delivery'),
            ('account.move', 'Vendor Bill'),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    source_res_id = fields.Integer(required=True, readonly=True, index=True)
    source_display_name = fields.Char(readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    user_id = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
        index=True,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='Vendor PDF / Attachment',
        domain="[('id', 'in', available_attachment_ids)]",
        help='Select the vendor PDF being tallied. Marks are virtual and do not alter the attachment.',
    )
    attachment_preview_html = fields.Html(
        string='Attachment Preview',
        compute='_compute_attachment_preview_html',
        sanitize=False,
        readonly=True,
    )
    available_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_available_attachment_ids',
    )
    line_ids = fields.One2many(
        'vendor.document.tally.mark',
        'session_id',
        string='Tally Marks',
        copy=False,
    )
    odoo_line_ids = fields.One2many(
        'vendor.document.tally.mark',
        'session_id',
        string='Odoo Lines',
        domain=[('source_side', '=', 'odoo_line')],
        copy=False,
    )
    pdf_line_ids = fields.One2many(
        'vendor.document.tally.mark',
        'session_id',
        string='PDF Lines',
        domain=[('source_side', '=', 'pdf_line')],
        copy=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('reviewed', 'Reviewed'),
            ('closed', 'Closed'),
        ],
        default='draft',
        required=True,
        tracking=True,
    )
    note = fields.Text(string='Tally Notes')
    mismatch_count = fields.Integer(compute='_compute_counts', store=True)
    checked_count = fields.Integer(compute='_compute_counts', store=True)
    line_count = fields.Integer(compute='_compute_counts', store=True)

    _sql_constraints = [
        (
            'source_user_unique',
            'unique(source_model, source_res_id, user_id)',
            'Only one open virtual tally session is allowed per user and source document.',
        ),
    ]

    @api.depends('source_model', 'source_display_name')
    def _compute_name(self):
        labels = dict(self._fields['source_model'].selection)
        for session in self:
            session.name = _('%(document_type)s Tally: %(document)s') % {
                'document_type': labels.get(session.source_model, session.source_model),
                'document': session.source_display_name or session.source_res_id,
            }

    @api.depends('line_ids.mark_type', 'line_ids.source_side')
    def _compute_counts(self):
        mismatch_marks = {'qty_mismatch', 'price_mismatch', 'not_on_pdf', 'pdf_only', 'duplicate', 'needs_review'}
        for session in self:
            odoo_lines = session.line_ids.filtered(lambda line: line.source_side == 'odoo_line')
            session.line_count = len(odoo_lines)
            session.checked_count = len(odoo_lines.filtered(lambda line: line.mark_type == 'checked'))
            session.mismatch_count = len(session.line_ids.filtered(lambda line: line.mark_type in mismatch_marks))

    def _compute_available_attachment_ids(self):
        Attachment = self.env['ir.attachment']
        for session in self:
            if not session.source_model or not session.source_res_id:
                session.available_attachment_ids = Attachment
                continue
            session.available_attachment_ids = session._get_source_attachments()

    @api.depends('attachment_id', 'attachment_id.mimetype')
    def _compute_attachment_preview_html(self):
        for session in self:
            attachment = session.attachment_id
            if not attachment:
                session.attachment_preview_html = (
                    '<div class="alert alert-info">'
                    'Select a vendor PDF / attachment to preview it here.'
                    '</div>'
                )
                continue

            url = '/web/content/%s?download=false' % attachment.id
            name = html_escape(attachment.name or _('Attachment'))
            mimetype = attachment.mimetype or ''
            if mimetype == 'application/pdf' or (attachment.name or '').lower().endswith('.pdf'):
                session.attachment_preview_html = (
                    '<iframe src="%s" title="%s" '
                    'style="width:100%%; min-height:760px; border:0;"></iframe>'
                ) % (url, name)
            elif mimetype.startswith('image/'):
                session.attachment_preview_html = (
                    '<img src="%s" alt="%s" style="max-width:100%%; height:auto;"/>'
                ) % (url, name)
            else:
                session.attachment_preview_html = (
                    '<div class="alert alert-info">'
                    '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
                    '</div>'
                ) % (url, name)

    def _get_source_attachments(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            return self.env['ir.attachment']
        return self.env['ir.attachment'].search([
            ('res_model', '=', self.source_model),
            ('res_id', '=', self.source_res_id),
        ], order='id desc')

    @api.model
    def _get_or_create_for_record(self, record):
        record.ensure_one()
        _logger.info(
            '%s[OPEN][START] model=%s res_id=%s user_id=%s',
            TALLY_LOG_HEAD,
            record._name,
            record.id,
            self.env.user.id,
        )
        session = self.search([
            ('source_model', '=', record._name),
            ('source_res_id', '=', record.id),
            ('user_id', '=', self.env.user.id),
        ], limit=1)
        if not session:
            values = self._prepare_session_values(record)
            session = self.create(values)
            _logger.info(
                '%s[OPEN][END] created session_id=%s model=%s res_id=%s',
                TALLY_LOG_HEAD,
                session.id,
                record._name,
                record.id,
            )
        else:
            session.write(self._prepare_session_values(record))
            _logger.info(
                '%s[OPEN][END] reused session_id=%s model=%s res_id=%s',
                TALLY_LOG_HEAD,
                session.id,
                record._name,
                record.id,
            )
        if not session.attachment_id:
            attachment = session._get_source_attachments()[:1]
            if attachment:
                session.attachment_id = attachment.id
                _logger.info(
                    '%s[OPEN][ATTACHMENT] session_id=%s attachment_id=%s source_model=%s source_res_id=%s',
                    TALLY_LOG_HEAD,
                    session.id,
                    attachment.id,
                    record._name,
                    record.id,
                )
        session.action_refresh_lines()
        return session

    @api.model
    def _prepare_session_values(self, record):
        partner = getattr(record, 'partner_id', False)
        company = getattr(record, 'company_id', False)
        currency = (
            getattr(record, 'currency_id', False)
            or getattr(company, 'currency_id', False)
        )
        return {
            'source_model': record._name,
            'source_res_id': record.id,
            'source_display_name': record.display_name,
            'partner_id': partner.id if partner else False,
            'company_id': company.id if company else False,
            'currency_id': currency.id if currency else False,
        }

    def _get_source_record(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id or self.source_model not in self.env:
            return self.env['ir.model'].browse()
        return self.env[self.source_model].browse(self.source_res_id).exists()

    def _source_line_values(self):
        self.ensure_one()
        source = self._get_source_record()
        if not source:
            return []
        if self.source_model == 'purchase.order':
            return self._purchase_order_line_values(source)
        if self.source_model == 'stock.picking':
            return self._stock_picking_line_values(source)
        if self.source_model == 'account.move':
            return self._account_move_line_values(source)
        return []

    def _common_line_values(self, line, sequence, quantity_ordered=0.0, quantity_received=0.0, quantity_billed=0.0):
        product = getattr(line, 'product_id', False)
        uom = (
            getattr(line, 'product_uom', False)
            or getattr(line, 'product_uom_id', False)
        )
        currency = (
            getattr(line, 'currency_id', False)
            or self.currency_id
            or self.company_id.currency_id
        )
        unit_price = getattr(line, 'price_unit', 0.0) or 0.0
        final_unit_price = (
            getattr(line, 'final_unit_price_vat_incl', 0.0)
            or getattr(line, 'net_price', 0.0)
            or unit_price
        )
        total = (
            getattr(line, 'price_total', 0.0)
            or getattr(line, 'receipt_grade_amount_vat_incl', 0.0)
            or 0.0
        )
        return {
            'sequence': sequence,
            'source_side': 'odoo_line',
            'source_model': line._name,
            'source_res_id': line.id,
            'source_key': '%s:%s' % (line._name, line.id),
            'product_id': product.id if product else False,
            'description': getattr(line, 'name', False) or (product.display_name if product else False),
            'product_uom_id': uom.id if uom else False,
            'quantity_ordered': quantity_ordered or 0.0,
            'quantity_received': quantity_received or 0.0,
            'quantity_billed': quantity_billed or 0.0,
            'unit_price': unit_price,
            'final_unit_price': final_unit_price,
            'line_total': total,
            'currency_id': currency.id if currency else False,
        }

    def _purchase_order_line_values(self, order):
        values = []
        for sequence, line in enumerate(order.order_line.filtered(lambda item: not item.display_type), start=1):
            values.append(self._common_line_values(
                line,
                sequence,
                quantity_ordered=line.product_qty,
                quantity_received=line.qty_received,
                quantity_billed=line.qty_invoiced,
            ))
        return values

    def _stock_picking_line_values(self, picking):
        values = []
        moves = picking.move_ids_without_package or picking.move_ids
        for sequence, move in enumerate(moves.filtered(lambda item: not item.scrapped), start=1):
            done_qty = getattr(move, 'quantity_done', 0.0) or getattr(move, 'quantity', 0.0) or 0.0
            purchase_line = getattr(move, 'purchase_line_id', False)
            values.append(self._common_line_values(
                move,
                sequence,
                quantity_ordered=move.product_uom_qty,
                quantity_received=done_qty,
                quantity_billed=purchase_line.qty_invoiced if purchase_line else 0.0,
            ))
        return values

    def _account_move_line_values(self, move):
        values = []
        lines = move.invoice_line_ids.filtered(lambda item: item.display_type not in ('line_section', 'line_note'))
        for sequence, line in enumerate(lines, start=1):
            purchase_line = line.purchase_line_id
            values.append(self._common_line_values(
                line,
                sequence,
                quantity_ordered=purchase_line.product_qty if purchase_line else 0.0,
                quantity_received=purchase_line.qty_received if purchase_line else 0.0,
                quantity_billed=line.quantity,
            ))
        return values

    def action_refresh_lines(self):
        Mark = self.env['vendor.document.tally.mark']
        for session in self:
            _logger.info(
                '%s[REFRESH][START] session_id=%s model=%s res_id=%s',
                TALLY_LOG_HEAD,
                session.id,
                session.source_model,
                session.source_res_id,
            )
            source_values = session._source_line_values()
            active_keys = {values['source_key'] for values in source_values}
            existing_by_key = {
                mark.source_key: mark
                for mark in session.line_ids.filtered(lambda item: item.source_side == 'odoo_line')
            }
            for values in source_values:
                values['session_id'] = session.id
                existing = existing_by_key.get(values['source_key'])
                if existing:
                    existing.write({
                        key: value
                        for key, value in values.items()
                        if key not in ('session_id', 'source_side', 'source_model', 'source_res_id', 'source_key')
                    })
                else:
                    Mark.create(values)

            stale = session.line_ids.filtered(
                lambda item: item.source_side == 'odoo_line' and item.source_key not in active_keys
            )
            if stale:
                stale.write({'active': False})
            _logger.info(
                '%s[REFRESH][END] session_id=%s source_line_count=%s stale_count=%s',
                TALLY_LOG_HEAD,
                session.id,
                len(source_values),
                len(stale),
            )
        return True

    def action_mark_reviewed(self):
        self.write({'state': 'reviewed'})
        return True

    def action_close(self):
        self.write({'state': 'closed'})
        return True

    def action_open_source_document(self):
        self.ensure_one()
        source = self._get_source_record()
        if not source:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.source_display_name or _('Source Document'),
            'res_model': self.source_model,
            'view_mode': 'form',
            'res_id': source.id,
            'target': 'current',
        }


class VendorDocumentTallyMark(models.Model):
    _name = 'vendor.document.tally.mark'
    _description = 'Vendor Document Tally Mark'
    _order = 'source_side desc, sequence asc, id asc'

    session_id = fields.Many2one(
        'vendor.document.tally.session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    source_side = fields.Selection(
        [
            ('odoo_line', 'Odoo Line'),
            ('pdf_line', 'PDF Line'),
        ],
        required=True,
        default='odoo_line',
        index=True,
    )
    source_model = fields.Char(readonly=True, index=True)
    source_res_id = fields.Integer(readonly=True, index=True)
    source_key = fields.Char(index=True)
    mark_type = fields.Selection(
        [
            ('unmarked', 'Unmarked'),
            ('checked', 'Checked'),
            ('crossed', 'Crossed Out'),
            ('question', 'Question'),
            ('qty_mismatch', 'Qty Mismatch'),
            ('price_mismatch', 'Price Mismatch'),
            ('not_on_pdf', 'Not on PDF'),
            ('pdf_only', 'PDF Only'),
            ('duplicate', 'Duplicate'),
            ('needs_review', 'Needs Review'),
        ],
        default='unmarked',
        required=True,
        index=True,
    )
    product_id = fields.Many2one('product.product', readonly=True)
    description = fields.Char(readonly=True)
    product_uom_id = fields.Many2one('uom.uom', readonly=True)
    quantity_ordered = fields.Float(readonly=True)
    quantity_received = fields.Float(readonly=True)
    quantity_billed = fields.Float(readonly=True)
    unit_price = fields.Monetary(currency_field='currency_id', readonly=True)
    final_unit_price = fields.Monetary(currency_field='currency_id', readonly=True)
    line_total = fields.Monetary(currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    attachment_id = fields.Many2one(
        'ir.attachment',
        string='PDF Attachment',
        domain="[('id', 'in', session_id.available_attachment_ids)]",
    )
    pdf_page_number = fields.Integer(default=1)
    pdf_line_reference = fields.Char(string='PDF Line / Item Code')
    pdf_text = fields.Char(string='Printed PDF Text')
    linked_mark_id = fields.Many2one(
        'vendor.document.tally.mark',
        string='Linked Odoo Line',
        domain="[('session_id', '=', session_id), ('source_side', '=', 'odoo_line')]",
    )
    note = fields.Text()

    def action_open_source_line(self):
        self.ensure_one()
        _logger.info(
            '%s[OPEN_LINE][START] mark_id=%s source_model=%s source_res_id=%s',
            TALLY_LOG_HEAD,
            self.id,
            self.source_model,
            self.source_res_id,
        )
        if not self.source_model or not self.source_res_id or self.source_model not in self.env:
            _logger.warning('%s[OPEN_LINE][ERROR] mark_id=%s reason=missing_source', TALLY_LOG_HEAD, self.id)
            return {'type': 'ir.actions.act_window_close'}
        source = self.env[self.source_model].browse(self.source_res_id).exists()
        if not source:
            _logger.warning('%s[OPEN_LINE][ERROR] mark_id=%s reason=not_found', TALLY_LOG_HEAD, self.id)
            return {'type': 'ir.actions.act_window_close'}
        _logger.info('%s[OPEN_LINE][END] mark_id=%s', TALLY_LOG_HEAD, self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tally Source Line'),
            'res_model': self.source_model,
            'view_mode': 'form',
            'res_id': source.id,
            'target': 'current',
        }
