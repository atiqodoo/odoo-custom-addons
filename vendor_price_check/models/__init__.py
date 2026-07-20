# -*- coding: utf-8 -*-
import logging


_logger = logging.getLogger(__name__)

from . import account_move
from . import account_move_line
from . import res_config_settings
from . import vendor_price_discrepancy
from . import purchase_order
from . import crown_invoice_audit

_logger.debug('[VPC_LOAD] models_imported')
