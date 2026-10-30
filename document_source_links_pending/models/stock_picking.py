import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    document_source_pending_id = fields.Many2one(
        'paint.pending.collection', string='Source Pending Collection',
        readonly=True, copy=True, index=True, check_company=True,
        ondelete='set null',
        help='Navigation relationship; does not change native POS picking membership.',
    )

    @api.constrains('document_source_pending_id', 'company_id')
    def _check_document_source_pending_company(self):
        # stock.picking checks company at confirmation rather than every create.
        # Validate this new relation immediately using the ORM's standard check;
        # it also permits stock users to carry an unreadable link on backorders.
        self._check_company(['document_source_pending_id'])

    @api.model_create_multi
    def create(self, vals_list):
        pending_id = self.env.context.get('document_source_pending_id')
        if pending_id:
            pending = self.env['paint.pending.collection'].browse(pending_id).exists()
            pending.check_access('read')
            origins = self._pending_source_origins(pending) if pending else set()
            vals_list = [dict(vals) for vals in vals_list]
            for vals in vals_list:
                picking_type = self.env['stock.picking.type'].browse(vals.get('picking_type_id'))
                if (vals.get('origin') in origins and picking_type.code == 'internal'
                        and picking_type.company_id == pending.company_id):
                    vals.setdefault('document_source_pending_id', pending.id)
            _logger.debug('[SOURCE_LINKS_PENDING][CAPTURE][START] collection_id=%s count=%s',
                          pending_id, len(vals_list))
        try:
            records = super().create(vals_list)
        except Exception:
            if pending_id:
                _logger.debug('[SOURCE_LINKS_PENDING][CAPTURE][ERROR] collection_id=%s outcome=failed', pending_id)
            raise
        if pending_id:
            _logger.debug('[SOURCE_LINKS_PENDING][CAPTURE][END] collection_id=%s picking_ids=%s',
                          pending_id, records.ids)
        return records

    @api.model
    def _pending_source_origins(self, pending):
        """Exact formats written by the upstream addon, for legacy compatibility only."""
        pending.ensure_one()
        return {f'{pending.pos_reference} - {pending.name}',
                f'Collection: {pending.name}', f'Return: {pending.name}'}

    def _get_source_pending_collections(self):
        """Resolve a batch of transfers with one inverse and one legacy lookup."""
        model = self.env['paint.pending.collection']
        if not model.has_access('read'):
            return model
        collections = self.document_source_pending_id._filtered_access('read')
        unresolved = self.filtered(lambda p: not p.document_source_pending_id
                                   and p.picking_type_code == 'internal')
        if not unresolved:
            return collections
        # Older holding transfers already have an authoritative inverse relation.
        lines = self.env['paint.pending.collection.line']
        if lines.has_access('read'):
            linked = lines.search([
                ('stock_move_id.picking_id', 'in', unresolved.ids),
                ('pending_collection_id.company_id', 'in', unresolved.company_id.ids),
            ])
            collections |= linked.pending_collection_id._filtered_access('read')
            unresolved -= linked.stock_move_id.picking_id
        # Legacy collection/cancellation pickings retained only an origin string.
        names = {}
        for picking in unresolved:
            origin = picking.origin or ''
            if origin.startswith('Collection: '):
                names[picking.id] = origin.removeprefix('Collection: ')
            elif origin.startswith('Return: '):
                names[picking.id] = origin.removeprefix('Return: ')
            elif ' - ' in origin:
                names[picking.id] = origin.rsplit(' - ', 1)[1]
        if not names:
            return collections
        candidates = model.search([
            ('name', 'in', list(set(names.values()))),
            ('company_id', 'in', unresolved.company_id.ids),
        ])
        grouped = {}
        for candidate in candidates:
            key = (candidate.company_id.id, candidate.name)
            grouped[key] = grouped.get(key, model) | candidate
        for picking in unresolved:
            matches = grouped.get((picking.company_id.id, names.get(picking.id)), model)
            if len(matches) == 1 and picking.origin in self._pending_source_origins(matches):
                collections |= matches
        return collections

    def _get_source_link_records(self):
        sources = super()._get_source_link_records()
        collections = self._get_source_link_pickings()._get_source_pending_collections()
        for pending in collections:
            if pending.has_access('read') and self._source_link_same_company(pending):
                sources.append((self.env._('Pending Collection'), pending))
                if pending.pos_order_id:
                    sources.append((self.env._('POS Order'), pending.pos_order_id))
        return sources

    @api.depends('document_source_pending_id', 'document_source_pending_id.pos_order_id',
                 'company_id', 'picking_type_code')
    def _compute_source_link_data(self):
        return super()._compute_source_link_data()
