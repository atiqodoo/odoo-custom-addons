import logging
from contextlib import contextmanager

from odoo.exceptions import AccessError

_logger = logging.getLogger('odoo.addons.account_cheque_book_management')
# An in-process capability, never a client-supplied context flag.
TOKEN = object()


def require_group(records, group):
    if not records.env.user.has_group('account_cheque_book_management.' + group):
        raise AccessError(records.env._('You do not have permission for this cheque operation.'))
    records.check_access('write')
    if records.filtered(lambda r: r.company_id not in records.env.companies):
        raise AccessError(records.env._('Select the cheque company before continuing.'))


@contextmanager
def operation(records, name):
    context = (records._name, records.ids, records.env.uid, records.env.company.id)
    _logger.debug('[CHEQUE_BOOK][%s][START] model=%s ids=%s user_id=%s company_id=%s', name, *context)
    try:
        with records.env.cr.savepoint():
            yield
    except Exception as error:
        _logger.debug('[CHEQUE_BOOK][%s][ERROR] model=%s ids=%s user_id=%s company_id=%s error_type=%s', name, *context, type(error).__name__)
        raise
    _logger.debug('[CHEQUE_BOOK][%s][END] model=%s ids=%s user_id=%s company_id=%s', name, *context)
