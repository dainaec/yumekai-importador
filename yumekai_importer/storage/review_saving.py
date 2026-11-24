"""Save independent drafts without letting one rejected row block the rest."""
from yumekai_importer.storage.catalog_api import CatalogRequestError


def save_review_drafts(api, products, result, progress=None):
    """Split only definite, rolled-back validation/conflict rejections.

    Timeouts and ambiguous server errors stop immediately. Confirmed successes
    remain in result so the UI never resubmits them with stale revisions.
    """
    def save(entries):
        if not entries:
            return
        try:
            response = api.review_products("save", entries)
        except CatalogRequestError as error:
            if error.status_code not in (400, 409, 422):
                raise
            if len(entries) > 1:
                middle = len(entries) // 2
                save(entries[:middle])
                save(entries[middle:])
            else:
                result["failed"].append({"original_isbn": entries[0]["original_isbn"],
                                         "message": str(error), "status_code": error.status_code})
                if progress:
                    progress(result)
            return
        result["saved"].extend(response["saved"])
        if progress:
            progress(result)

    save(list(products))
