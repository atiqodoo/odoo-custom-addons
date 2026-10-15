# -*- coding: utf-8 -*-

import logging

from odoo import models


_logger = logging.getLogger(__name__)


class VirtualQuotationLogMixin(models.AbstractModel):
    _name = 'virtual.quotation.log.mixin'
    _description = 'Virtual Quotation Logging Helper'

    LOG_HEAD = 'VIRTUAL QUOTATION'

    def _vq_log(self, operation, message='', level='info', **payload):
        parts = ['=' * 18, self.LOG_HEAD, operation]
        if message:
            parts.append(message)
        parts.append('=' * 18)
        log_message = ' | '.join(parts)
        if payload:
            log_message = '%s | %s' % (log_message, payload)
        getattr(_logger, level)(log_message)
