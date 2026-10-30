{
    "name": "POS Cheque Deposit Control",
    "version": "18.0.1.1.0",
    "category": "Point of Sale",
    "summary": "Due cheque reminders and mandatory bank deposit receipts",
    "license": "LGPL-3",
    "depends": ["pos_uncleared_payment_guard", "point_of_sale", "account"],
    "data": [
        "security/cheque_deposit_security.xml",
        "views/pos_config_views.xml",
        "views/pos_payment_method_views.xml",
        "views/account_move_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_cheque_deposit_control/static/src/app/cheque_deposit_reminder.js",
            "pos_cheque_deposit_control/static/src/app/cheque_deposit_reminder.xml",
        ],
    },
    "installable": True,
    "application": False,
}
