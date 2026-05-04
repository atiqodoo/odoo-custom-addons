# -*- coding: utf-8 -*-
"""
Migration: 18.0.1.0.1 — pre-migrate
=====================================

PURPOSE:
    Remove a stale ir.ui.view record that was created in a previous version
    of paint_pos_pending_collection. The record references a list view for
    'register.deferred.collection.wizard' with a field 'name' that does not
    exist on that model.

    Because Odoo validates ALL existing view records from the database against
    the current model schema BEFORE any XML data files are processed during
    an upgrade, the <delete> tag approach in XML is too late — the validation
    crash occurs first.

    A pre-migrate script runs via raw SQL before the ORM and view registry
    are loaded, making it the correct tool for this class of problem.

STALE RECORD DETAILS:
    xml_id  : paint_pos_pending_collection.view_register_deferred_collection_wizard_list
    model   : register.deferred.collection.wizard
    bad field referenced: 'name' (does not exist on wizard)

ERROR THIS FIXES:
    odoo.tools.convert.ParseError:
        Field "name" does not exist in model "register.deferred.collection.wizard"
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Delete the stale list view record and its ir.model.data entry via raw SQL.

    This runs before the ORM initialises and before any view validation occurs,
    which is the only reliable way to prevent the ParseError caused by a DB
    view record referencing a non-existent field.

    Args:
        cr  : Database cursor provided by Odoo's migration framework.
        version (str): Previous module version string (may be None on first run).

    Steps:
        1. Find the ir.ui.view record ID linked to the stale xml_id.
        2. Delete that ir.ui.view row.
        3. Delete the corresponding ir.model.data row.
        4. Log the outcome at INFO level.
    """
    _logger.info(
        "[MIGRATION 18.0.1.0.1] pre-migrate: "
        "Starting cleanup of stale list view "
        "'view_register_deferred_collection_wizard_list'."
    )

    # Step 1: Find the ir.ui.view ID from ir.model.data
    cr.execute("""
        SELECT res_id
        FROM ir_model_data
        WHERE module = 'paint_pos_pending_collection'
          AND name   = 'view_register_deferred_collection_wizard_list'
          AND model  = 'ir.ui.view'
        LIMIT 1
    """)
    row = cr.fetchone()

    if row:
        view_id = row[0]
        _logger.info(
            "[MIGRATION 18.0.1.0.1] pre-migrate: "
            "Found stale ir.ui.view ID = %s. Deleting...",
            view_id,
        )

        # Step 2: Delete the ir.ui.view record
        cr.execute(
            "DELETE FROM ir_ui_view WHERE id = %s",
            (view_id,),
        )
        _logger.info(
            "[MIGRATION 18.0.1.0.1] pre-migrate: "
            "ir.ui.view ID %s deleted.",
            view_id,
        )

        # Step 3: Delete the ir.model.data entry
        cr.execute("""
            DELETE FROM ir_model_data
            WHERE module = 'paint_pos_pending_collection'
              AND name   = 'view_register_deferred_collection_wizard_list'
              AND model  = 'ir.ui.view'
        """)
        _logger.info(
            "[MIGRATION 18.0.1.0.1] pre-migrate: "
            "ir.model.data entry for stale view deleted."
        )

    else:
        _logger.info(
            "[MIGRATION 18.0.1.0.1] pre-migrate: "
            "Stale view record not found in ir.model.data "
            "(already cleaned up or never existed). Nothing to do."
        )

    _logger.info(
        "[MIGRATION 18.0.1.0.1] pre-migrate: "
        "Cleanup complete."
    )