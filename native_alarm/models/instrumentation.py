"""Safe operation boundary logging shared by alarm models."""
from functools import wraps
import logging
from time import monotonic

_logger = logging.getLogger(__name__)


def logged_operation(operation):
    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            start = monotonic()
            _logger.debug('[NATIVE_ALARM][%s][START] model=%s ids=%s user_id=%s',
                          operation, self._name, self.ids, self.env.uid)
            try:
                result = method(self, *args, **kwargs)
            except Exception as exc:
                _logger.debug('[NATIVE_ALARM][%s][ERROR] model=%s type=%s',
                              operation, self._name, type(exc).__name__)
                raise
            _logger.debug('[NATIVE_ALARM][%s][END] model=%s ids=%s duration_ms=%.1f',
                          operation, self._name, getattr(result, 'ids', self.ids), (monotonic() - start) * 1000)
            return result
        return wrapped
    return decorate
