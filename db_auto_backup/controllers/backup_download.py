import logging
import os

from odoo import http, _
from odoo.exceptions import AccessDenied
from odoo.http import request, Response

try:
    from werkzeug.utils import send_file
except ImportError:
    from odoo.tools._vendor.send_file import send_file

_logger = logging.getLogger(__name__)


class DbBackupDownloadController(http.Controller):

    @http.route('/db_auto_backup/download/<int:history_id>', type='http', auth='user')
    def download_backup(self, history_id):
        if not request.env.user.has_group('base.group_system'):
            _logger.warning(
                '[DB_AUTO_BACKUP][DOWNLOAD][ERROR] history_id=%s reason=unauthorized user_id=%s',
                history_id, request.env.user.id)
            raise AccessDenied()

        history = request.env['db.backup.history'].browse(history_id).exists()
        if not history:
            return request.not_found()

        backup_path = history._get_existing_backup_path()
        if not backup_path:
            return request.not_found()

        _logger.info(
            '[DB_AUTO_BACKUP][DOWNLOAD][START] history_id=%s path=%s user_id=%s',
            history.id, backup_path, request.env.user.id)
        return send_file(
            backup_path,
            request.httprequest.environ,
            download_name=history.name or os.path.basename(backup_path),
            as_attachment=True,
            response_class=Response,
        )
