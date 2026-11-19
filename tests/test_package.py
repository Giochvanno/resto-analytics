import resto_analytics


def test_version_is_semver() -> None:
    major, minor, patch = resto_analytics.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
