{
    'name':    'M-Pesa C2B POS',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'M-Pesa C2B payment validation and reconciliation in POS',
    'depends': ['point_of_sale', 'mpesa_c2b_sms', 'pos_uncleared_payment_guard', 'pos_cod'],
    'data': [
        'security/ir.model.access.csv',
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'mpesa_c2b_pos/static/src/services/MpesaValidationService.js',
            'mpesa_c2b_pos/static/src/components/MpesaPaymentScreen/MpesaPaymentScreen.xml',
            'mpesa_c2b_pos/static/src/components/MpesaPaymentScreen/MpesaPaymentScreen.js',
            'mpesa_c2b_pos/static/src/components/MpesaTransactionCard/MpesaTransactionCard.xml',
            'mpesa_c2b_pos/static/src/components/MpesaTransactionCard/MpesaTransactionCard.js',
            'mpesa_c2b_pos/static/src/components/MpesaManagerPin/MpesaManagerPin.xml',
            'mpesa_c2b_pos/static/src/components/MpesaManagerPin/MpesaManagerPin.js',
            'mpesa_c2b_pos/static/src/utils/mpesa_payment_dialog.js',
            'mpesa_c2b_pos/static/src/patches/payment_screen_mpesa_patch.js',
            'mpesa_c2b_pos/static/src/patches/settle_due_mpesa_patch.js',
            'mpesa_c2b_pos/static/src/patches/deposit_mpesa_validation_patch.js',
            'mpesa_c2b_pos/static/src/patches/cod_mpesa_collection_patch.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
