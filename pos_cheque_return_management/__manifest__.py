{
    "name": "POS Cheque Returns and Recovery",
    "version": "18.0.1.0.0",
    "category": "Point of Sale",
    "license": "LGPL-3",
    "depends": ["pos_uncleared_payment_guard", "pos_cod_deposit_settlement", "account", "mail"],
    "data": [
        "security/security.xml", "security/ir.model.access.csv",
        "views/cheque_views.xml", "views/hold_views.xml", "wizard/workflow_views.xml",
    ],
    "assets": {"point_of_sale._assets_pos": ["pos_cheque_return_management/static/src/cheque_return.scss"]},
    "installable": True,
    "application": False,
}
