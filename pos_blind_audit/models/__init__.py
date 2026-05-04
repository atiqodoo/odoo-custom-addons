# -*- coding: utf-8 -*-
"""
pos_blind_audit.models package initialiser.

Import order matters for Odoo's model registry: pos_config is loaded
first so that its fields exist before pos_session references them via
``config_id.limit_variance`` and ``config_id.variance_amount``.
"""
from . import pos_config
from . import pos_session
from . import pos_blind_audit_attempt
