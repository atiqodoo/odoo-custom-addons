"""
SMS parser — strategy pattern.
Each class handles one known M-Pesa SMS template variant.
Add new formats by creating a new class and registering it in SmsParserEngine.
No Odoo ORM dependency — pure Python, independently testable.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

_log = logging.getLogger(__name__)
NAIROBI_UTC_OFFSET = timedelta(hours=3)


def _kenya_local_to_utc_naive(value: datetime) -> datetime:
    """Odoo stores naive datetimes as UTC; Safaricom SMS time is Kenya local."""
    return value - NAIROBI_UTC_OFFSET


@dataclass
class ParsedTransaction:
    mpesa_ref:        str
    amount:           float
    sender_name:      str
    sender_phone:     str
    transaction_date: datetime
    utility_balance:  float
    transaction_cost: float
    raw_text:         str


class BuyGoodsParserV1:
    """
    Handles current Safaricom BuyGoods confirmation format.
    Example:
      QJK8HKPL3R Confirmed. Ksh500.00 received from JOHN DOE
      254712345678 on 22/5/26 at 10:30 AM. New Utility balance
      is Ksh5,000.00. Transaction cost, Ksh0.00.
    """

    _PATTERN = re.compile(
        r'(?P<ref>[A-Z0-9]{10})\s+Confirmed\.\s+'
        r'Ksh\s*(?P<amount>[\d,]+\.?\d*)\s+received\s+from\s+'
        r'(?P<name>[A-Z][A-Z\s]+?)\s+'
        r'(?P<phone>(?:254|\+254|0)\d{9})'
        r'\s+on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})'
        r'\s+at\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)\.'
        r'(?:.*?New\s+(?:Account|Utility)\s+balance\s+is\s+Ksh\s*(?P<balance>[\d,]+\.?\d*)\.)?'
        r'(?:.*?cost,\s*Ksh\s*(?P<cost>[\d,]+\.?\d*)\.)?',
        re.DOTALL | re.IGNORECASE,
    )

    def can_parse(self, text: str) -> bool:
        return bool(self._PATTERN.search(text))

    def parse(self, text: str) -> Optional[ParsedTransaction]:
        m = self._PATTERN.search(text)
        if not m:
            return None
        txn_date = self._parse_date(m.group('date'), m.group('time'))
        return ParsedTransaction(
            mpesa_ref=m.group('ref').strip().upper(),
            amount=self._money(m.group('amount')),
            sender_name=m.group('name').strip().title(),
            sender_phone=self._normalise_phone(m.group('phone')),
            transaction_date=txn_date,
            utility_balance=self._money(m.group('balance') or '0.00'),
            transaction_cost=self._money(m.group('cost') or self._extract_cost(text)),
            raw_text=text,
        )

    @staticmethod
    def _money(s: str) -> float:
        return float(s.replace(',', ''))

    @staticmethod
    def _extract_cost(text: str) -> str:
        match = re.search(
            r'Transaction\s*cost,\s*Ksh\s*([\d,]+\.?\d*)\.',
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else '0.00'

    @staticmethod
    def _normalise_phone(p: str) -> str:
        digits = re.sub(r'\D', '', p)
        if digits.startswith('254') and len(digits) == 12:
            return digits
        if digits.startswith('0') and len(digits) == 10:
            return '254' + digits[1:]
        return digits

    @staticmethod
    def _parse_date(date_str: str, time_str: str) -> datetime:
        combined = f"{date_str.strip()} {time_str.strip()}"
        for fmt in ('%d/%m/%y %I:%M %p', '%d/%m/%Y %I:%M %p',
                    '%d/%m/%y %I:%M%p', '%d/%m/%Y %I:%M%p'):
            try:
                return _kenya_local_to_utc_naive(datetime.strptime(combined, fmt))
            except ValueError:
                continue
        _log.warning("Could not parse date '%s' — using now()", combined)
        return datetime.utcnow()


class BuyGoodsParserV2:
    """
    Handles Safaricom format where the date appears before the amount.
    """

    _PATTERN = re.compile(
        r'(?P<ref>[A-Z0-9]{10})\s+Confirmed\.?\s*'
        r'on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})'
        r'\s+at\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s*'
        r'Ksh\s*(?P<amount>[\d,]+\.?\d*)\s+received\s+from\s+'
        r'(?P<phone>(?:254|\+254|0)\d{9})\s+'
        r'(?P<name>.+?)\.'
        r'(?:\s+New\s+(?:Account|Utility)\s+balance\s+is\s+Ksh\s*(?P<balance>[\d,]+\.?\d*)\.)?'
        r'(?:.*?Transaction\s*cost,\s*Ksh\s*(?P<cost>[\d,]+\.?\d*)\.)?',
        re.DOTALL | re.IGNORECASE,
    )

    def can_parse(self, text: str) -> bool:
        return bool(self._PATTERN.search(text))

    def parse(self, text: str) -> Optional[ParsedTransaction]:
        m = self._PATTERN.search(text)
        if not m:
            return None
        txn_date = BuyGoodsParserV1._parse_date(m.group('date'), m.group('time'))
        return ParsedTransaction(
            mpesa_ref=m.group('ref').strip().upper(),
            amount=BuyGoodsParserV1._money(m.group('amount')),
            sender_name=m.group('name').strip().title(),
            sender_phone=BuyGoodsParserV1._normalise_phone(m.group('phone')),
            transaction_date=txn_date,
            utility_balance=BuyGoodsParserV1._money(m.group('balance') or '0.00'),
            transaction_cost=BuyGoodsParserV1._money(m.group('cost') or BuyGoodsParserV1._extract_cost(text)),
            raw_text=text,
        )


class SmsParserEngine:
    """
    Tries registered parsers in order.
    Returns first successful parse or None (→ raw log flagged 'failed').
    Register new variant parsers by appending to _parsers.
    """

    def __init__(self):
        self._parsers = [BuyGoodsParserV1(), BuyGoodsParserV2()]

    def parse(self, text: str) -> Optional[ParsedTransaction]:
        for parser in self._parsers:
            if parser.can_parse(text):
                result = parser.parse(text)
                if result:
                    _log.info(
                        "Parsed by %s: ref=%s amount=%.2f",
                        parser.__class__.__name__,
                        result.mpesa_ref,
                        result.amount,
                    )
                    return result
        _log.warning("No parser matched SMS: %.80r", text)
        return None
