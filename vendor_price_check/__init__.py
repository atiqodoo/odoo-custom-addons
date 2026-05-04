# ============================================================================
# FILE: vendor_price_check/__init__.py (ROOT)
# ============================================================================
# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

_logger.info("=" * 80)
_logger.info("🔧 Loading vendor_price_check module")
_logger.info("=" * 80)

from . import models
_logger.info("✓ Loaded models package")

from . import wizard
_logger.info("✓ Loaded wizard package")

_logger.info("=" * 80)