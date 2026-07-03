"""PII redaction and non-English script filtering module (Phase 2)."""

import logging
import re
from typing import List, Dict
from pulse.ingestion.models import Review

logger = logging.getLogger(__name__)


def is_latin_dominant(text: str, min_ascii_ratio: float = 0.80) -> bool:
    """Check if the text is predominantly Latin/ASCII (e.g., dropping Devanagari while keeping Hinglish)."""
    if not text:
        return True
    ascii_chars = sum(1 for c in text if c.isascii())
    return (ascii_chars / len(text)) >= min_ascii_ratio


def filter_scripts(reviews: List[Review], min_ascii_ratio: float = 0.80) -> List[Review]:
    """Drop reviews where ASCII character ratio is below threshold (e.g. Devanagari script)."""
    filtered = []
    dropped_count = 0
    for rev in reviews:
        if is_latin_dominant(rev.text, min_ascii_ratio=min_ascii_ratio):
            filtered.append(rev)
        else:
            dropped_count += 1
    if dropped_count > 0:
        logger.info(f"Script filter dropped {dropped_count} reviews (ASCII ratio < {min_ascii_ratio * 100:.0f}%).")
    return filtered


# PII Regex patterns
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', re.IGNORECASE)
PHONE_REGEX = re.compile(
    r'(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{9}\b|'
    r'(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{2}[\-\s]?\d{3}[\-\s]?\d{4}\b|'
    r'(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{4}[\-\s]?\d{5}\b'
)
# PAN card: 5 letters, 4 digits, 1 letter. Aadhaar / long numeric IDs: 12 to 18 digits.
ID_REGEX = re.compile(
    r'\b[A-Z]{5}\d{4}[A-Z]\b|'
    r'\b\d{4}[\-\s]?\d{4}[\-\s]?\d{4}\b|'
    r'\b\d{12,18}\b',
    re.IGNORECASE
)
URL_REGEX = re.compile(r'(https?://[a-zA-Z0-9.-]+|www\.[a-zA-Z0-9.-]+)/[^\s]+', re.IGNORECASE)


def scrub_pii(reviews: List[Review]) -> List[Review]:
    """Redact email addresses, phone numbers, and long numeric IDs from review text."""
    scrubbed_reviews = []
    counts: Dict[str, int] = {"EMAIL": 0, "PHONE": 0, "ID": 0, "URL": 0}

    for rev in reviews:
        text = rev.text

        # Redact URLs with tokens/paths
        text, n_url = URL_REGEX.subn(r'\1/[URL]', text)
        counts["URL"] += n_url

        # Redact Emails
        text, n_email = EMAIL_REGEX.subn('[EMAIL]', text)
        counts["EMAIL"] += n_email

        # Redact PAN / Aadhaar / Long IDs
        text, n_id = ID_REGEX.subn('[ID]', text)
        counts["ID"] += n_id

        # Redact Indian phone numbers
        text, n_phone = PHONE_REGEX.subn('[PHONE]', text)
        counts["PHONE"] += n_phone

        scrubbed_reviews.append(Review(text=text, rating=rev.rating))

    logger.info(
        f"PII scrubbing completed. Redactions - Emails: {counts['EMAIL']}, "
        f"Phones: {counts['PHONE']}, IDs: {counts['ID']}, URLs: {counts['URL']}."
    )
    return scrubbed_reviews
