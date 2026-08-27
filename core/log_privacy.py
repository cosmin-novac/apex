"""Keep the user's portfolio out of the server log.

Logs leave the process: the hosting platform collects them, retains them,
and streams them to anyone with access to the deployment, none of which is
under this app's control. So a log line names no instrument, no quantity and
no amount. Debugging a sync needs stages, counts and failures, and those are
what it gets.

Two things live here.

`anon` is what the app's own log lines use in place of an ISIN, a ticker or
an instrument name. It is keyed with random bytes generated at import, so
one instrument reads the same way through a single run and cannot be
reversed, matched to a security, or lined up with another run or another
worker. That keeps the log followable without it saying what anything is.

`install_log_privacy` is the net underneath. Third-party code logs too, and
pytr quotes the human-readable event description ("Could not parse fees from
<fund name> Verkaufsorder") on every event it cannot parse. Those never
reach a handler intact. Everything else that passes through gets euro
amounts and ISIN-shaped tokens taken out, so a line added later, here or in
a dependency, cannot quietly start leaking.
"""

import hashlib
import logging
import os
import re

# New on every start. Nothing derived from it survives a restart, which is
# the point: a handle in yesterday's log cannot be lined up with one today.
_KEY = os.urandom(16)

# Loggers whose messages carry instrument names as a matter of course.
_UNSAFE_LOGGERS = ("pytr.event",)

_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
# "€1.234,56", "-1234.56 EUR", "1,234.56EUR"
_MONEY = re.compile(
    r"(?:[€$£]\s?-?\d[\d.,]*)|(?:-?\d[\d.,]*\s?(?:EUR|USD|GBP|CHF)\b)")


def anon(value, prefix: str = "sec") -> str:
    """A short handle for an instrument, safe to put in a log line."""
    if value in (None, ""):
        return prefix + ":?"
    digest = hashlib.blake2s(str(value).encode("utf-8", "replace"),
                             key=_KEY, digest_size=3).hexdigest()
    return prefix + ":" + digest


def _scrub(text: str) -> str:
    text = _ISIN.sub(lambda m: anon(m.group(0)), text)
    return _MONEY.sub("<amount>", text)


class PortfolioPrivacyFilter(logging.Filter):
    """Drops or scrubs anything that would put holdings in the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        name = record.name or ""
        if any(name == u or name.startswith(u + ".") for u in _UNSAFE_LOGGERS):
            if not record.args:
                # The values are already baked into the message and there is
                # no way to tell them from the rest of it. Say nothing.
                return False
            # Keep the static half ("Could not parse fees from %s"), which is
            # the part that says what went wrong, and drop what it names.
            record.args = tuple("<redacted>" for _ in
                                (record.args if isinstance(record.args, tuple)
                                 else (record.args,)))
            return True

        try:
            message = record.getMessage()
        except Exception:
            return True                     # let logging report its own fault
        scrubbed = _scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_privacy(logger: logging.Logger = None) -> None:
    """Attach the filter to every handler on *logger* (root by default).

    Handlers rather than the logger itself: a filter on a logger only sees
    what is logged through that logger, while a handler sees everything that
    reaches it, including records that propagated up from libraries.
    """
    logger = logger or logging.getLogger()
    for handler in logger.handlers:
        if not any(isinstance(f, PortfolioPrivacyFilter) for f in handler.filters):
            handler.addFilter(PortfolioPrivacyFilter())
