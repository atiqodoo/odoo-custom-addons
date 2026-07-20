# -*- coding: utf-8 -*-

import logging
import os

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LocalDocumentPathValidator(models.AbstractModel):
    _name = 'local.document.path.validator'
    _description = 'Local Document Path Validator'

    def normalize_path(self, path):
        if not path:
            return False
        return os.path.normpath(os.path.expandvars(os.path.expanduser(path.strip())))

    def ensure_directory(self, path, label):
        normalized = self.normalize_path(path)
        if not normalized:
            raise UserError(_('%s is required.') % label)
        if not os.path.isdir(normalized):
            _logger.warning('LDI_PATH_INVALID label=%s path=%s', label, normalized)
            raise UserError(_('%s does not exist or is not a directory: %s') % (label, normalized))
        return normalized

    def ensure_file_under_root(self, root_path, file_path):
        root_real = os.path.realpath(self.normalize_path(root_path))
        file_real = os.path.realpath(self.normalize_path(file_path))
        try:
            common = os.path.commonpath([root_real, file_real])
        except ValueError:
            return False
        return common == root_real
