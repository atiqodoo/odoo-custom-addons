# -*- coding: utf-8 -*-

from io import BytesIO

from markupsafe import escape

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - fallback for older local environments
    try:
        from PyPDF2 import PdfReader
    except ImportError:  # pragma: no cover
        PdfReader = None

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class VirtualQuotation(models.Model):
    _name = 'virtual.quotation'
    _description = 'Virtual Print Quotation'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'virtual.quotation.log.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True, tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('finalized', 'Finalized'), ('cancelled', 'Cancelled')],
        default='draft',
        required=True,
        tracking=True,
    )
    partner_id = fields.Many2one('res.partner', string='Customer / Contact', tracking=True)
    linked_sale_order_id = fields.Many2one(
        'sale.order',
        string='Linked Real Quotation',
        copy=False,
        tracking=True,
        help='Optional link to an operational Odoo quotation.',
    )
    date_order = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    validity_date = fields.Date(tracking=True)
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        compute='_compute_pricelist_id',
        store=True,
        readonly=False,
        default=lambda self: self._default_pricelist_id(),
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        store=True,
        readonly=False,
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms')
    user_id = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )
    note = fields.Html()
    line_ids = fields.One2many(
        'virtual.quotation.line',
        'quotation_id',
        string='Lines',
        copy=True,
    )
    amount_untaxed = fields.Monetary(compute='_compute_amounts', store=True)
    amount_tax = fields.Monetary(compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(compute='_compute_amounts', store=True)
    line_count = fields.Integer(compute='_compute_line_count')
    below_cost_warning_html = fields.Html(
        string='Below Cost Warning',
        compute='_compute_below_cost_warning_html',
        sanitize=False,
    )

    @api.model
    def _default_pricelist_id(self):
        partner = self.env.user.partner_id
        return (
            partner.property_product_pricelist
            or self.env['product.pricelist'].search([], limit=1)
        )

    @api.depends('partner_id')
    def _compute_pricelist_id(self):
        for quotation in self:
            if quotation.pricelist_id:
                continue
            quotation.pricelist_id = (
                quotation.partner_id.property_product_pricelist
                or self.env['product.pricelist'].search([], limit=1)
            )

    @api.depends('pricelist_id', 'company_id')
    def _compute_currency_id(self):
        for quotation in self:
            quotation.currency_id = (
                quotation.pricelist_id.currency_id
                or quotation.company_id.currency_id
                or self.env.company.currency_id
            )

    @api.depends('line_ids.price_subtotal', 'line_ids.price_tax', 'line_ids.price_total')
    def _compute_amounts(self):
        for quotation in self:
            lines = quotation.line_ids.filtered(lambda line: not line.display_type)
            quotation.amount_untaxed = sum(lines.mapped('price_subtotal'))
            quotation.amount_tax = sum(lines.mapped('price_tax'))
            quotation.amount_total = sum(lines.mapped('price_total'))

    def _compute_line_count(self):
        for quotation in self:
            quotation.line_count = len(quotation.line_ids)

    @api.depends(
        'line_ids.product_id',
        'line_ids.product_uom_qty',
        'line_ids.product_uom_id',
        'line_ids.price_unit',
        'line_ids.discount',
        'line_ids.tax_id',
        'line_ids.price_total',
        'currency_id',
        'company_id',
        'date_order',
    )
    def _compute_below_cost_warning_html(self):
        for quotation in self:
            violations = quotation._get_below_cost_line_violations()
            quotation.below_cost_warning_html = (
                quotation._prepare_below_cost_warning_html(violations)
                if violations
                else False
            )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env.ref(
            'virtual_quotation_print.sequence_virtual_quotation',
            raise_if_not_found=False,
        )
        for values in vals_list:
            if values.get('name', 'New') == 'New':
                values['name'] = sequence.next_by_id() if sequence else self.env['ir.sequence'].next_by_code('virtual.quotation') or 'New'
            self._ensure_monetary_create_values(values)
        records = super().create(vals_list)
        records._vq_log('CREATE DONE', ids=records.ids)
        return records

    def write(self, values):
        self._guard_finalized_write(values)
        result = super().write(values)
        self._vq_log('WRITE DONE', ids=self.ids, values=values)
        return result

    def unlink(self):
        protected = self.filtered(lambda quotation: quotation.state == 'finalized')
        if protected:
            raise UserError(_('Finalized virtual quotations cannot be deleted. Cancel them instead.'))
        self._vq_log('UNLINK', ids=self.ids)
        return super().unlink()

    def action_add_manual_line(self):
        self.ensure_one()
        self._ensure_draft()
        line_values = self.env['virtual.quotation.service'].prepare_manual_line_values(
            self,
            _('Manual Item'),
            quantity=1.0,
            price_unit=0.0,
        )
        self.env['virtual.quotation.line'].create(line_values)
        return True

    def action_add_section_line(self):
        self.ensure_one()
        self._ensure_draft()
        self.env['virtual.quotation.line'].create({
            'quotation_id': self.id,
            'display_type': 'line_section',
            'name': _('New Section'),
            'sequence': self._get_next_line_sequence(),
        })
        return True

    def action_add_note_line(self):
        self.ensure_one()
        self._ensure_draft()
        self.env['virtual.quotation.line'].create({
            'quotation_id': self.id,
            'display_type': 'line_note',
            'name': _('New Note'),
            'sequence': self._get_next_line_sequence(),
        })
        return True

    def action_open_import_sale_order_wizard(self):
        self.ensure_one()
        self._ensure_draft()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Load Real Quotation Lines'),
            'res_model': 'virtual.quotation.import.sale.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_target_quotation_id': self.id,
                'default_sale_order_id': self.linked_sale_order_id.id,
                'active_model': self._name,
                'active_id': self.id,
            },
        }

    def action_open_discount_wizard(self):
        self.ensure_one()
        self._ensure_draft()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Discount'),
            'res_model': 'virtual.quotation.discount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_quotation_id': self.id,
                'active_model': self._name,
                'active_id': self.id,
            },
        }

    def action_finalize(self):
        for quotation in self:
            quotation._ensure_draft()
            if not quotation.line_ids.filtered(lambda line: not line.display_type):
                raise UserError(_('Add at least one quotation line before finalizing.'))
            quotation._check_registered_variant_prices_not_below_cost('Finalize')
            quotation.state = 'finalized'
            quotation.message_post(body=_('Virtual quotation finalized for printout.'))
            quotation._vq_log('FINALIZED', quotation_id=quotation.id, total=quotation.amount_total)
        return True

    def action_reset_to_draft(self):
        self._vq_log('RESET TO DRAFT START', ids=self.ids, user_id=self.env.uid)
        self.write({'state': 'draft'})
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_print_virtual_quotation(self):
        return self._action_print_virtual_document('quotation')

    def action_print_virtual_invoice(self):
        return self._action_print_virtual_document('invoice')

    def _action_print_virtual_document(self, document_type='quotation'):
        self.ensure_one()
        document_type = document_type if document_type in ('quotation', 'invoice') else 'quotation'
        blocked_action = _('Print %(document_type)s PDF', document_type=document_type.title())
        self._check_registered_variant_prices_not_below_cost(blocked_action)
        report = self.env.ref('virtual_quotation_print.action_report_virtual_quotation')
        report = report.with_context(virtual_quotation_document_type=document_type)
        pdf_mode, page_counts = self._select_pdf_fit_mode(report)
        self._vq_log(
            'PRINT PDF',
            quotation_id=self.id,
            document_type=document_type,
            total=self.amount_total,
            pdf_mode=pdf_mode,
            page_counts=page_counts,
        )
        report = report.with_context(
            virtual_quotation_pdf_mode=pdf_mode,
            virtual_quotation_page_counts=page_counts,
            virtual_quotation_document_type=document_type,
        )
        return report.report_action(self)

    def action_create_real_quotation(self):
        self.ensure_one()
        order = self.env['virtual.quotation.service'].create_real_sale_order(self)
        return {
            'type': 'ir.actions.act_window',
            'name': order.display_name,
            'res_model': 'sale.order',
            'res_id': order.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_linked_sale_order(self):
        self.ensure_one()
        if not self.linked_sale_order_id:
            raise UserError(_('No real quotation is linked.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.linked_sale_order_id.display_name,
            'res_model': 'sale.order',
            'res_id': self.linked_sale_order_id.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }

    def _ensure_draft(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft virtual quotations can be edited.'))

    def _get_next_line_sequence(self):
        self.ensure_one()
        return (max(self.line_ids.mapped('sequence') or [0]) + 10)

    def _check_registered_variant_prices_not_below_cost(self, operation):
        self.ensure_one()
        violations = self._get_below_cost_line_violations()
        if not violations:
            return
        self._vq_log(
            'BELOW COST BLOCK',
            quotation_id=self.id,
            blocked_action=operation,
            violations=[
                {
                    'line_id': violation['line'].id,
                    'product_id': violation['line'].product_id.id,
                    'sale_price_incl_vat': violation['sale_price_incl_vat'],
                    'cost_price_incl_vat': violation['cost_price_incl_vat'],
                }
                for violation in violations
            ],
            level='warning',
        )
        raise UserError(self._prepare_below_cost_warning_text(operation, violations))

    def _get_below_cost_line_violations(self):
        self.ensure_one()
        violations = []
        currency = self.currency_id or self.company_id.currency_id or self.env.company.currency_id
        for line in self._get_registered_variant_cost_guard_lines():
            sale_price_incl_vat = self._get_line_unit_sale_price_incl_vat(line)
            cost_price_incl_vat = self._get_line_unit_cost_price_incl_vat(line)
            if not cost_price_incl_vat:
                continue
            if float_compare(
                sale_price_incl_vat,
                cost_price_incl_vat,
                precision_rounding=currency.rounding,
            ) < 0:
                violations.append({
                    'line': line,
                    'sale_price_incl_vat': sale_price_incl_vat,
                    'cost_price_incl_vat': cost_price_incl_vat,
                })
        return violations

    def _get_registered_variant_cost_guard_lines(self):
        self.ensure_one()
        return self.line_ids.filtered(
            lambda line: (
                not line.display_type
                and not line.is_discount_line
                and line.product_id
                and line.product_uom_qty > 0.0
            )
        )

    def _get_line_unit_sale_price_incl_vat(self, line):
        quantity = line.product_uom_qty or 1.0
        if line.price_total:
            return (line.currency_id or self.currency_id).round(line.price_total / quantity)
        return self.env['virtual.quotation.service'].compute_line_amounts(line)['price_total'] / quantity

    def _get_line_unit_cost_price_incl_vat(self, line):
        product = line.product_id.with_company(line.company_id or self.company_id)
        company = line.company_id or self.company_id or self.env.company
        currency = line.currency_id or self.currency_id or company.currency_id
        cost = product.standard_price or 0.0
        if line.product_uom_id and line.product_uom_id != product.uom_id:
            cost = product.uom_id._compute_price(cost, line.product_uom_id)
        if company.currency_id != currency:
            cost = company.currency_id._convert(
                cost,
                currency,
                company,
                (self.date_order or fields.Datetime.now()).date(),
            )
        if line.tax_id:
            tax_result = line.tax_id.compute_all(
                cost,
                currency=currency,
                quantity=1.0,
                product=product,
                partner=self.partner_id,
                handle_price_include=False,
            )
            cost = tax_result.get('total_included', cost)
        return currency.round(cost)

    def _prepare_below_cost_warning_text(self, operation, violations):
        self.ensure_one()
        lines = [
            _('Cannot %(operation)s because registered product lines are below cost price including VAT.', operation=operation),
            '',
            _('Update the unit price or discount before continuing:'),
        ]
        for violation in violations[:10]:
            line = violation['line']
            lines.append(
                _(
                    '- %(product)s: selling %(sale)s, cost %(cost)s',
                    product=line.product_id.display_name,
                    sale=self._format_report_amount(violation['sale_price_incl_vat']),
                    cost=self._format_report_amount(violation['cost_price_incl_vat']),
                )
            )
        if len(violations) > 10:
            lines.append(_('...and %(count)s more line(s).', count=len(violations) - 10))
        return '\n'.join(lines)

    def _prepare_below_cost_warning_html(self, violations):
        self.ensure_one()
        items = []
        for violation in violations[:5]:
            line = violation['line']
            items.append(
                '<li>%s: selling %s, cost %s</li>' % (
                    escape(line.product_id.display_name),
                    escape(self._format_report_amount(violation['sale_price_incl_vat'])),
                    escape(self._format_report_amount(violation['cost_price_incl_vat'])),
                )
            )
        extra = ''
        if len(violations) > 5:
            extra = '<li>%s</li>' % escape(_('...and %(count)s more line(s).', count=len(violations) - 5))
        return (
            '<div class="alert alert-warning mb-3" role="alert">'
            '<strong>%s</strong><br/>%s<ul class="mb-0">%s%s</ul></div>'
        ) % (
            escape(_('Below cost warning')),
            escape(_('Finalize and Print PDF are blocked until these registered product lines are at or above cost price including VAT.')),
            ''.join(items),
            extra,
        )

    def _select_pdf_fit_mode(self, report):
        page_counts = {}
        normal_page_count = self._safe_pdf_page_count(report, 'normal')
        page_counts['normal'] = normal_page_count
        if normal_page_count <= 1:
            return 'normal', page_counts

        fit_page_count = self._safe_pdf_page_count(report, 'fit')
        page_counts['fit'] = fit_page_count
        if fit_page_count <= 1:
            return 'fit', page_counts

        compact_page_count = self._safe_pdf_page_count(report, 'compact')
        page_counts['compact'] = compact_page_count
        return 'compact', page_counts

    def _safe_pdf_page_count(self, report, pdf_mode):
        page_count = self._get_pdf_page_count(report, pdf_mode)
        try:
            page_count = int(page_count or 1)
        except (TypeError, ValueError):
            page_count = 1
        return max(page_count, 1)

    def _get_pdf_page_count(self, report, pdf_mode):
        if not PdfReader:
            self._vq_log(
                'PDF PAGE COUNT SKIPPED',
                'No PDF reader library available; using normal report sizing.',
                level='warning',
                quotation_id=self.id,
            )
            return 1
        try:
            pdf_content, _content_type = report.with_context(
                virtual_quotation_pdf_mode=pdf_mode,
                discard_logo_check=True,
            )._render_qweb_pdf(report.report_name, res_ids=self.ids)
            reader = PdfReader(BytesIO(pdf_content))
            return len(reader.pages)
        except Exception as exc:
            self._vq_log(
                'PDF PAGE COUNT FAILED',
                'Using normal report sizing.',
                level='warning',
                quotation_id=self.id,
                pdf_mode=pdf_mode,
                error=str(exc),
            )
            return 1

    def _format_report_amount(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        symbol = currency.symbol or currency.name or ''
        return '%s %s' % ('{:,.2f}'.format(amount or 0.0), symbol)

    def _guard_finalized_write(self, values):
        if values.get('state') == 'draft':
            protected = self.filtered(lambda quotation: quotation.state != 'draft')
            if protected and not self.env.user.has_group('virtual_quotation_print.group_virtual_quotation_manager'):
                raise UserError(_('Only virtual quotation managers can reset documents to draft.'))
        editable_fields = {'state', 'message_follower_ids', 'activity_ids', 'message_ids'}
        business_fields = set(values) - editable_fields
        if business_fields and any(quotation.state == 'finalized' for quotation in self):
            raise UserError(_('Finalized virtual quotations are read-only. Reset to draft first.'))

    @api.model
    def _ensure_monetary_create_values(self, values):
        if not values.get('pricelist_id'):
            partner = self.env['res.partner'].browse(values.get('partner_id')).exists()
            pricelist = (
                partner.property_product_pricelist
                if partner
                else self._default_pricelist_id()
            )
            if pricelist:
                values['pricelist_id'] = pricelist.id

        if not values.get('currency_id'):
            pricelist = self.env['product.pricelist'].browse(values.get('pricelist_id')).exists()
            company = self.env['res.company'].browse(values.get('company_id')).exists() or self.env.company
            currency = pricelist.currency_id or company.currency_id or self.env.company.currency_id
            values['currency_id'] = currency.id


class VirtualQuotationLine(models.Model):
    _name = 'virtual.quotation.line'
    _description = 'Virtual Print Quotation Line'
    _inherit = 'virtual.quotation.log.mixin'
    _order = 'quotation_id, sequence, id'

    quotation_id = fields.Many2one(
        'virtual.quotation',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    display_type = fields.Selection(
        [('line_section', 'Section'), ('line_note', 'Note')],
        default=False,
    )
    product_id = fields.Many2one('product.product', string='Product / Service')
    is_manual_item = fields.Boolean(default=False)
    is_discount_line = fields.Boolean(default=False, copy=False)
    name = fields.Text(required=True)
    product_uom_qty = fields.Float(default=1.0, string='Quantity')
    product_uom_id = fields.Many2one('uom.uom', string='UoM')
    price_unit = fields.Float(string='Unit Price', digits='Product Price')
    discount = fields.Float(string='Disc.%')
    tax_id = fields.Many2many('account.tax', string='Taxes')
    currency_id = fields.Many2one(related='quotation_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(related='quotation_id.company_id', store=True, readonly=True)
    metadata_json = fields.Json(
        string='Extension Metadata',
        copy=True,
        help='Structured extension payload for tinting, APS, imports or external systems.',
    )
    price_subtotal = fields.Monetary(compute='_compute_amounts', store=True)
    price_tax = fields.Monetary(compute='_compute_amounts', store=True)
    price_total = fields.Monetary(compute='_compute_amounts', store=True)
    section_subtotal = fields.Monetary(
        string='Section Subtotal',
        compute='_compute_section_subtotal',
        help='Tax-included subtotal for product lines below this section until the next section.',
    )

    @api.depends('product_uom_qty', 'price_unit', 'discount', 'tax_id', 'quotation_id.partner_id', 'currency_id')
    def _compute_amounts(self):
        service = self.env['virtual.quotation.service']
        for line in self:
            if line.display_type:
                line.price_subtotal = line.price_tax = line.price_total = 0.0
                continue
            amounts = service.compute_line_amounts(line)
            line.price_subtotal = amounts['price_subtotal']
            line.price_tax = amounts['price_tax']
            line.price_total = amounts['price_total']

    @api.depends(
        'quotation_id.line_ids.sequence',
        'quotation_id.line_ids.display_type',
        'quotation_id.line_ids.price_total',
    )
    def _compute_section_subtotal(self):
        lines_by_quote = {}
        for line in self:
            if line.quotation_id:
                lines_by_quote.setdefault(line.quotation_id, self.env['virtual.quotation.line'])
                lines_by_quote[line.quotation_id] |= line.quotation_id.line_ids
            else:
                line.section_subtotal = 0.0

        section_totals = {}
        for quotation, quote_lines in lines_by_quote.items():
            current_section = self.env['virtual.quotation.line']
            for quote_line in quote_lines.sorted(lambda item: (item.sequence, item.id or 0)):
                if quote_line.display_type == 'line_section':
                    current_section = quote_line
                    section_totals[quote_line.id] = 0.0
                elif not quote_line.display_type and current_section:
                    section_totals[current_section.id] = (
                        section_totals.get(current_section.id, 0.0)
                        + quote_line.price_total
                    )

        for line in self:
            line.section_subtotal = (
                line.currency_id.round(section_totals.get(line.id, 0.0))
                if line.display_type == 'line_section' and line.currency_id
                else 0.0
            )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if not line.product_id or not line.quotation_id:
                continue
            values = self.env['virtual.quotation.service'].prepare_product_line_values(
                line.quotation_id,
                line.product_id,
                line.product_uom_qty or 1.0,
            )
            values.pop('quotation_id', None)
            line.update(values)

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            quotation = self.env['virtual.quotation'].browse(values.get('quotation_id')).exists()
            if quotation:
                quotation._ensure_draft()
            if values.get('display_type'):
                self._clear_accountable_values(values)
        lines = super().create(vals_list)
        lines._vq_log('LINE CREATE DONE', ids=lines.ids)
        return lines

    def write(self, values):
        for line in self:
            line.quotation_id._ensure_draft()
        if values.get('display_type'):
            values = dict(values)
            self._clear_accountable_values(values)
        result = super().write(values)
        self._vq_log('LINE WRITE DONE', ids=self.ids, values=values)
        return result

    def unlink(self):
        for line in self:
            line.quotation_id._ensure_draft()
        self._vq_log('LINE UNLINK', ids=self.ids)
        return super().unlink()

    @api.model
    def _clear_accountable_values(self, values):
        values.update({
            'product_id': False,
            'is_manual_item': False,
            'product_uom_qty': 0.0,
            'product_uom_id': False,
            'price_unit': 0.0,
            'discount': 0.0,
            'tax_id': [(5, 0, 0)],
        })
