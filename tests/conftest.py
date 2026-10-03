"""Pytest helpers.

The test classes are plain classes that use unittest-style
``self.assertIsNotNone``; provide that assertion on collection.
"""


def _assert_is_not_none(self, obj, msg=None):
    if obj is None:
        raise AssertionError(msg or "expected non-None result, got None")


def pytest_collection_modifyitems(items):
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is not None and not hasattr(cls, "assertIsNotNone"):
            cls.assertIsNotNone = _assert_is_not_none
