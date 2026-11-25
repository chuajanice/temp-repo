"""Pure consumer rules (Phase 5, Slice 1). No Django import, so tests can run without a database."""

DEFAULT_PENALTY_CODE = "P001"   # the legacy views' default penalty code


def next_consumer_id(max_consumer_id):
    """Legacy rule: last = int(prefix of the highest consumer_id); new id = 10-digit prefix + '-01'.

    max_consumer_id: the highest existing consumer_id, or None when there are no connections.
    The legacy code crashes on an empty table; this rule starts at 1 instead (documented deviation).
    """
    last = 0 if max_consumer_id is None else int(str(max_consumer_id).split("-")[0])
    return "%010d-01" % (last + 1)
