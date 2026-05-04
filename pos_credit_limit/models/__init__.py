# -*- coding: utf-8 -*-
# res.partner extensions
# Import order sets the MRO chain for _load_pos_data_fields:
#   res_partner_payment_terms -> res_partner_credit -> base res.partner
from . import res_partner_credit
from . import res_partner_payment_terms

# pos.payment.method extension — separate model, loaded after partner models
from . import pos_payment_method_type
