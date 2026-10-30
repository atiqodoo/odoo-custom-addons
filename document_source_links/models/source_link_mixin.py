import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)


class DocumentSourceLinkMixin(models.AbstractModel):
    _name = 'document.source.link.mixin'
    _description = 'Document source navigation contract'

    source_link_data = fields.Json(
        string='Linked Sources', compute='_compute_source_link_data',
        compute_sudo=False, readonly=True,
    )

    def _get_source_link_records(self):
        """Extend with super(): return [(translated role, singleton record), ...].

        Providers must use explicit relationships, respect read access while
        traversing them, and avoid writes. This hook never accepts client data.
        """
        self.ensure_one()
        return []

    def _source_link_same_company(self, record):
        """Shared records are allowed; company documents stay in their company."""
        company = record.company_id if 'company_id' in record._fields else False
        owner = self.company_id if 'company_id' in self._fields else False
        return not company or (
            company in self.env.companies and (not owner or company == owner)
        )

    def _get_visible_source_links(self):
        self.ensure_one()
        self.check_access('read')
        _logger.debug('[SOURCE_LINKS][RESOLVE][START] model=%s id=%s', self._name, self.id)
        result, seen = [], set()
        try:
            candidates = self._get_source_link_records()
        except Exception as error:
            _logger.debug('[SOURCE_LINKS][RESOLVE][ERROR] model=%s id=%s error_type=%s',
                          self._name, self.id, type(error).__name__)
            raise
        for role, record in candidates:
            record = record.with_env(self.env)
            record.ensure_one()
            key = (record._name, record.id)
            if key in seen or key == (self._name, self.id):
                continue
            seen.add(key)
            try:
                if not record.exists() or not record.has_access('read'):
                    continue
                if not self._source_link_same_company(record):
                    continue
                result.append({
                    'model': record._name, 'id': record.id,
                    'role': role, 'name': record.display_name,
                })
            except (AccessError, MissingError):
                # Labels and IDs of inaccessible targets never reach the client.
                _logger.debug('[SOURCE_LINKS][RESOLVE][ERROR] model=%s id=%s outcome=unavailable_target',
                              self._name, self.id)
        _logger.debug('[SOURCE_LINKS][RESOLVE][END] model=%s id=%s count=%s',
                      self._name, self.id, len(result))
        return result

    @api.depends_context('uid', 'company', 'allowed_company_ids', 'lang')
    def _compute_source_link_data(self):
        for record in self:
            record.source_link_data = record._get_visible_source_links() if record.id else []

    def action_open_source_link(self, source_model, source_id):
        """Re-resolve on every click: client IDs confer no authority."""
        self.ensure_one()
        _logger.debug('[SOURCE_LINKS][OPEN][START] model=%s id=%s', self._name, self.id)
        try:
            sources = self._get_visible_source_links()
            source = next((item for item in sources if
                           item['model'] == source_model and item['id'] == source_id), None)
            if not source:
                raise AccessError(_('This source document is unavailable or you cannot access it.'))
            action = {
                'type': 'ir.actions.act_window', 'name': source['role'],
                'res_model': source['model'], 'res_id': source['id'],
                'views': [(False, 'form')], 'target': 'current',
                'context': {'form_view_initial_mode': 'readonly'},
            }
        except (AccessError, MissingError):
            _logger.debug('[SOURCE_LINKS][OPEN][ERROR] model=%s id=%s outcome=unavailable',
                          self._name, self.id)
            raise
        _logger.debug('[SOURCE_LINKS][OPEN][END] model=%s id=%s outcome=opened', self._name, self.id)
        return action
