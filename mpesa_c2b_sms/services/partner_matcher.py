"""
Matches a normalised M-Pesa phone number to an existing res.partner.
Pure service; no HTTP, no direct model mutations.
"""
import logging
import re

_log = logging.getLogger(__name__)


class PartnerMatcher:
    """
    Lookup order:
      1. Exact match on res.partner.mobile using common Kenyan variants.
      2. Exact match on res.partner.phone using common Kenyan variants.
      3. Suffix match on the last 9 digits for contacts saved as 7XXXXXXXX.
    Returns the first match or an empty recordset.
    """

    def __init__(self, env):
        self._env = env

    def find(self, phone_254: str):
        """
        phone_254: normalised 254XXXXXXXXX string.
        Returns res.partner record or empty recordset.
        """
        if not phone_254:
            return self._env['res.partner'].browse()

        Partner = self._env['res.partner'].sudo()
        variants = self._phone_variants(phone_254)

        partner = Partner.search([('mobile', 'in', variants)], limit=1)
        if partner:
            _log.info("Partner matched by mobile: %s -> %s", phone_254, partner.name)
            return partner

        partner = Partner.search([('phone', 'in', variants)], limit=1)
        if partner:
            _log.info("Partner matched by phone: %s -> %s", phone_254, partner.name)
            return partner

        suffix = phone_254[-9:] if len(phone_254) >= 9 else phone_254
        partner = Partner.search([
            '|',
            ('mobile', 'ilike', suffix),
            ('phone', 'ilike', suffix),
        ], limit=1)
        if partner:
            _log.info("Partner matched by phone suffix: %s -> %s", phone_254, partner.name)
            return partner

        _log.info("No partner found for phone %s", phone_254)
        return Partner.browse()

    @staticmethod
    def _phone_variants(phone_254: str):
        digits = re.sub(r'\D', '', phone_254 or '')
        if digits.startswith('254') and len(digits) == 12:
            local = '0' + digits[3:]
            short = digits[3:]
            return [digits, '+' + digits, local, short]
        return [phone_254]
