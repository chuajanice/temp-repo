"""Business-database switch (Phase 5, Slice 1).

WB_BUSINESS_DB selects where business operations read and write:
  legacy      (default) the existing screens keep using the legacy tables. Nothing changes.
  normalized  the migrated screens use the normalized database (alias 'normalized').

Authentication stays on the legacy database in both modes.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

LEGACY = "legacy"
NORMALIZED = "normalized"
VALID_MODES = (LEGACY, NORMALIZED)


def business_mode():
    mode = str(getattr(settings, "WB_BUSINESS_DB", LEGACY)).strip().lower()
    if mode not in VALID_MODES:
        raise ImproperlyConfigured("WB_BUSINESS_DB must be 'legacy' or 'normalized', not %r." % mode)
    return mode


def use_normalized():
    return business_mode() == NORMALIZED
