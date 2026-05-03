"""Errors for snapshot backup / restore."""


class SnapshotError(Exception):
    """Base class for snapshot export/import failures."""


class UnsupportedFormatVersionError(SnapshotError):
    """Snapshot format_version is not supported by this release."""


class SchemaVersionMismatchError(SnapshotError):
    """Snapshot schema_version does not match the target database migrations."""


class SnapshotIntegrityError(SnapshotError):
    """Checksum, member list, or structural validation failed."""


class SnapshotValidationError(SnapshotError):
    """Snapshot data failed business rules (e.g. unbalanced journal)."""


class IncompleteSnapshotError(SnapshotError):
    """Required ZIP members or metadata fields are missing."""

