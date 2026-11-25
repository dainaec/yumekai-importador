"""Confirming a review discards unchecked fields; failed accepted fields survive."""


def confirm_change_selection(drafts, rows, selected, marked):
    discarded = 0
    for key, row in rows.items():
        draft = drafts.get(key)
        if draft is None:
            continue
        accepted = selected.get(key, {})
        for field in list(row["changes"]):
            if field not in accepted and field in draft["changes"]:
                draft["changes"].pop(field)
                discarded += 1
        draft.pop("save_error", None)
        if not draft["changes"]:
            drafts.pop(key)
        marked.discard(key)
    return discarded
