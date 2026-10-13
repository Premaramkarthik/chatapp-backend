"""Remove authorization callback query strings from HTTP access logs."""

import logging
import re


class CallbackRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value):
            if isinstance(value, str):
                return re.sub(
                    r"([?&](?:loginToken|code|state|session|access_token)=)[^\s&\"']+",
                    r"\1[REDACTED]",
                    value,
                )
            return value

        # Uvicorn's access formatter needs the original tuple structure.
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


def install_callback_redaction() -> None:
    logging.getLogger("uvicorn.access").addFilter(CallbackRedactionFilter())
