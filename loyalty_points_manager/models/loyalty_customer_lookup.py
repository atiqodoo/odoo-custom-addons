# -*- coding: utf-8 -*-
import re
import logging
from odoo import models, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# ── Phone normalization ───────────────────────────────────────────────────────
# Strip spaces, dashes, parentheses, dots that are purely cosmetic formatting.
_PHONE_STRIP_RE = re.compile(r'[\s\-\(\)\.]+')

# Minimum/maximum digit counts for a plausible phone number.
_MIN_DIGITS = 7
_MAX_DIGITS = 15


def _normalize_phone(raw):
    """
    Strip cosmetic formatting from a raw phone string.

    Keeps digits and a leading '+' (international prefix).
    Returns the cleaned string; does NOT raise — callers validate the result.
    """
    if not raw:
        return ''
    cleaned = _PHONE_STRIP_RE.sub('', str(raw).strip())
    return cleaned


def _is_valid_phone(phone):
    """
    True if `phone` has between _MIN_DIGITS and _MAX_DIGITS digits,
    optionally prefixed with '+'.
    """
    if not phone:
        return False
    digits_only = re.sub(r'\D', '', phone)
    return _MIN_DIGITS <= len(digits_only) <= _MAX_DIGITS


def _phone_variants(phone):
    """
    Return a set of common format variants for a normalised phone string.

    Handles the two most common local/international mismatches:
      • 0712345678  ↔  712345678        (leading-zero ↔ bare)
      • +254712345678 ↔ 254712345678   (international with/without '+')

    Country-code expansion (e.g. 254... → 0...) is intentionally omitted
    because the country prefix length varies and we don't know the base country.
    A simple digit-prefix match on the bare form is sufficient for most stores.
    """
    variants = {phone}

    if phone.startswith('+'):
        bare = phone[1:]                   # +254712345678 → 254712345678
        variants.add(bare)

    elif phone.startswith('0') and len(phone) >= _MIN_DIGITS + 1:
        variants.add(phone[1:])            # 0712345678 → 712345678

    elif phone.isdigit() and len(phone) >= _MIN_DIGITS:
        variants.add('0' + phone)          # 712345678 → 0712345678

    _logger.debug(
        "[loyalty_lookup] _phone_variants | input=%r | variants=%s",
        phone, variants,
    )
    return variants


def _build_phone_domain(candidates):
    """
    Build a flat Odoo OR-domain that matches `phone` OR `mobile` against
    every candidate in *candidates*.

    Uses Polish-prefix notation: (N-1) '|' operators followed by N atoms.
    For 4 atoms: ['|', '|', '|', A, B, C, D] ≡ A OR B OR C OR D.

    Returns a domain that always evaluates to False if *candidates* is empty.
    """
    if not candidates:
        return [('id', '=', False)]

    atoms = []
    for c in sorted(candidates):           # sorted for deterministic query plan
        atoms.append(('phone',  '=', c))
        atoms.append(('mobile', '=', c))

    if len(atoms) == 1:
        return atoms

    return ['|'] * (len(atoms) - 1) + atoms


class PosSessionLoyaltyLookup(models.Model):
    """
    Extends pos.session with a single @api.model method called from the POS
    PaymentScreen loyalty popup (payment_screen_loyalty_patch.js) via RPC.

    Using pos.session as the host model is intentional:
      • It is already accessible in the POS frontend's session context.
      • The operation is session-scoped (link a customer for the current checkout).
      • Keeps pos.order free from customer-creation logic.
    """
    _inherit = 'pos.session'

    # ── Partner fields returned to the POS frontend ───────────────────────────
    # Must be a superset of what PosOrder / loyalty engine accesses on a partner.
    _PARTNER_FIELDS = [
        'id', 'name', 'display_name',
        'phone', 'mobile', 'email',
        'street', 'city', 'zip',
        'state_id', 'country_id',
        'vat', 'barcode',
        'customer_rank',
        'write_date',
    ]

    @api.model
    def find_or_create_loyalty_customer(self, phone_raw, create_if_not_found=True):
        """
        Search for an existing partner by phone/mobile, and optionally create
        one if not found.  Called from POS JavaScript via RPC.

        Flow:
          1. Validate & normalise the raw phone string.
          2. Search res.partner by exact phone/mobile match.
          3. On miss: try common format variants (leading-zero / country-prefix).
          4a. If create_if_not_found=True and still not found: auto-create a
              minimal partner named "Loyalty Customer: <phone>" (legacy/quick path).
          4b. If create_if_not_found=False and not found: return found=False so
              the POS frontend can open the standard Odoo partner-creation form
              with the phone pre-filled (recommended path for new customers).
          5. Return a dict of partner fields the POS frontend needs.

        Args:
            phone_raw          (str|int): Raw phone/loyalty-ID from the POS popup.
            create_if_not_found (bool):  True  → auto-create minimal partner.
                                         False → return found=False, let UI handle.

        Returns:
            dict — one of two shapes:

            When found (or auto-created):
                found        (bool=True)
                partner_id   (int)
                name         (str)
                display_name (str)
                phone        (str)
                mobile       (str)
                email        (str)
                street       (str)
                city         (str)
                country_id   ([id, name] or [])
                state_id     ([id, name] or [])
                vat          (str)
                barcode      (str)
                write_date   (str ISO)
                customer_rank (int)
                is_new       (bool)  – True only when auto-created

            When not found and create_if_not_found=False:
                found        (bool=False)
                phone        (str)   – normalised, for pre-filling the UI form

        Raises:
            ValidationError: phone is empty or has no valid digit sequence.
        """
        _logger.info(
            "[loyalty_lookup] find_or_create_loyalty_customer called"
            " | raw_input=%r | create_if_not_found=%s | caller_session_id=%s",
            phone_raw, create_if_not_found, self.env.context.get('session_id', '?'),
        )

        # ── 1. Input validation ───────────────────────────────────────────────
        phone_raw = str(phone_raw).strip() if phone_raw else ''
        if not phone_raw:
            _logger.warning("[loyalty_lookup] Empty input — ValidationError raised")
            raise ValidationError("Phone number / loyalty ID cannot be empty.")

        phone = _normalize_phone(phone_raw)
        _logger.debug(
            "[loyalty_lookup] normalized | raw=%r → clean=%r", phone_raw, phone
        )

        if not _is_valid_phone(phone):
            _logger.warning(
                "[loyalty_lookup] Invalid phone | raw=%r | normalized=%r"
                " | digits=%d (expected %d–%d)",
                phone_raw, phone,
                len(re.sub(r'\D', '', phone)), _MIN_DIGITS, _MAX_DIGITS,
            )
            raise ValidationError(
                f"Invalid phone number: '{phone_raw}'. "
                f"Expected {_MIN_DIGITS}–{_MAX_DIGITS} digits, "
                "optionally prefixed with '+'."
            )

        Partner = self.env['res.partner']

        # ── 2. Primary search (exact normalized form) ─────────────────────────
        _logger.debug(
            "[loyalty_lookup] PRIMARY SEARCH | phone=%r (OR mobile)", phone
        )
        partner = Partner.sudo().search(
            ['|', ('phone', '=', phone), ('mobile', '=', phone)],
            limit=1,
        )

        if partner:
            _logger.info(
                "[loyalty_lookup] PRIMARY HIT"
                " | partner_id=%s | name=%r | phone=%r | mobile=%r",
                partner.id, partner.name, partner.phone, partner.mobile,
            )
        else:
            # ── 3. Variant search ─────────────────────────────────────────────
            variants = _phone_variants(phone)
            extra = variants - {phone}
            if extra:
                domain = _build_phone_domain(extra)
                _logger.debug(
                    "[loyalty_lookup] VARIANT SEARCH | candidates=%s | domain=%s",
                    extra, domain,
                )
                partner = Partner.sudo().search(domain, limit=1)
                if partner:
                    _logger.info(
                        "[loyalty_lookup] VARIANT HIT"
                        " | partner_id=%s | name=%r | matched_phone=%r | matched_mobile=%r"
                        " | searched_variants=%s",
                        partner.id, partner.name,
                        partner.phone, partner.mobile, extra,
                    )
                else:
                    _logger.info(
                        "[loyalty_lookup] VARIANT MISS | searched=%s", extra
                    )

        is_new = False

        if not partner:
            if not create_if_not_found:
                # ── 4b. Defer creation to the POS UI form ─────────────────────
                _logger.info(
                    "[loyalty_lookup] NOT FOUND + create_if_not_found=False"
                    " | phone=%r → returning found=False for UI form", phone,
                )
                return {
                    'found': False,
                    'phone': phone,
                }

            # ── 4a. Auto-create minimal partner (legacy / quick path) ─────────
            partner_name = f"Loyalty Customer: {phone}"
            create_vals = {
                'name':          partner_name,
                'phone':         phone,
                'mobile':        phone,
                'customer_rank': 1,
                'comment':       (
                    "Auto-created by POS loyalty popup. "
                    "Please update with full customer details."
                ),
            }
            _logger.info(
                "[loyalty_lookup] CREATING new partner | vals=%s", create_vals
            )
            try:
                partner = Partner.sudo().create(create_vals)
                is_new = True
                _logger.info(
                    "[loyalty_lookup] CREATED | partner_id=%s | name=%r",
                    partner.id, partner.name,
                )
            except Exception as exc:
                _logger.error(
                    "[loyalty_lookup] Partner creation FAILED | error=%s | vals=%s",
                    exc, create_vals,
                )
                raise ValidationError(
                    f"Could not create loyalty customer for '{phone}': {exc}"
                ) from exc

        # ── 5. Build response payload ─────────────────────────────────────────
        country = partner.country_id
        state   = partner.state_id

        result = {
            'found':         True,
            'partner_id':    partner.id,
            'name':          partner.name         or '',
            'display_name':  partner.display_name or partner.name or '',
            'phone':         partner.phone        or '',
            'mobile':        partner.mobile       or '',
            'email':         partner.email        or '',
            'street':        partner.street       or '',
            'city':          partner.city         or '',
            'zip':           partner.zip          or '',
            'country_id':    [country.id, country.name] if country else [],
            'state_id':      [state.id, state.name]     if state   else [],
            'vat':           partner.vat          or '',
            'barcode':       partner.barcode      or '',
            'write_date':    partner.write_date.isoformat() if partner.write_date else '',
            'customer_rank': partner.customer_rank or 0,
            'is_new':        is_new,
        }

        _logger.info(
            "[loyalty_lookup] RESPONSE"
            " | partner_id=%s | name=%r | is_new=%s"
            " | phone=%r | mobile=%r",
            result['partner_id'], result['name'], result['is_new'],
            result['phone'], result['mobile'],
        )
        _logger.debug("[loyalty_lookup] full result payload: %s", result)

        return result
