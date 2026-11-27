"""A user's explicit completion choice for the pending-data view."""
from yumekai_importer.catalog.review_quality import completeness_issues


def manually_complete(product):
    return product.get("manual_complete") in (True, 1, "1")


def pending_data_issues(product):
    return [] if manually_complete(product) else completeness_issues(product)
