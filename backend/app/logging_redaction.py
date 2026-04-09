import logging
import re

_BEARER = re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s]+", re.MULTILINE)
_STREAM_QS = re.compile(
    r"([?&])(?:sig|token)=[^&\s]*",
    re.IGNORECASE,
)


def _scrub(text: str) -> str:
    text = _BEARER.sub(r"\1[REDACTED]", text)
    text = _STREAM_QS.sub(r"\1[REDACTED]", text)
    return text


class SecretRedactFilter(logging.Filter):
    """
    Remove bearer tokens and stream signatures from log records (formatted message).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = _scrub(msg)
        record.msg = clean
        record.args = ()
        return True
