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

__all__ = ["ADAPTERS", "cpsc", "fda", "fsis", "nhtsa"]
