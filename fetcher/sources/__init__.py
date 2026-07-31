"""Per-agency adapters.

Each module exposes `AGENCY` and a `fetch(client, since, until, backfill)`
generator yielding NormalizedRecall objects. Nothing downstream needs to know
which agency it is dealing with.
"""

from . import cpsc, fda, fsis, nhtsa

ADAPTERS = {
    fda.AGENCY: fda,
    cpsc.AGENCY: cpsc,
    fsis.AGENCY: fsis,
    nhtsa.AGENCY: nhtsa,
}

# Sources excluded from a default run, with the reason.
#
# FSIS is behind Akamai bot protection that rejects every non-browser TLS
# fingerprint, so it fails 100% of the time (see docs/sources.md#3-usda-fsis).
# Leaving it in the default set would make the daily cron job fail every night,
# which would in turn stop the heartbeat commit -- and the heartbeat is the
# only thing keeping GitHub from disabling the schedule for inactivity. One
# permanently-broken source would therefore take down ingestion for the three
# working ones.
#
# It stays in ADAPTERS and can still be run explicitly with --agency FSIS.
# Remove it from this set once the endpoint is reachable again.
UNAVAILABLE = {fsis.AGENCY}

DEFAULT_AGENCIES = sorted(set(ADAPTERS) - UNAVAILABLE)

__all__ = ["ADAPTERS", "DEFAULT_AGENCIES", "UNAVAILABLE", "cpsc", "fda", "fsis", "nhtsa"]
