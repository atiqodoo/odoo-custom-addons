# ============================================================================
# FILE: vendor_price_check/models/__init__.py
# ============================================================================
# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

_logger.info("📦 Loading models...")

from . import account_move
_logger.info("  ✓ account_move")

from . import account_move_line
_logger.info("  ✓ account_move_line")

from . import res_config_settings
_logger.info("  ✓ res_config_settings")

from . import vendor_price_discrepancy
_logger.info("  ✓ vendor_price_discrepancy")

from . import purchase_order
_logger.info("  ✓ purchase_order")

_logger.info("✓ All models loaded")