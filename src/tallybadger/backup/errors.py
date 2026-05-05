"""Errors for snapshot backup / restore."""


class SnapshotError(Exception):
    """Base class for snapshot export/import failures."""


class UnsupportedFormatVersionError(SnapshotError):
    """Snapshot format_version is not supported by this release."""

    def __init__(self, message: str):
        super().__init__(
            "Unsupported snapshot format_version "
            "(see docs/backup-snapshot-format.md): "
            f"{message}"
        )


class SchemaVersionMismatchError(SnapshotError):
    """Snapshot ``schema_version`` is not compatible with the target database migrations."""

    def __init__(self, message: str):
        super().__init__(
            "Snapshot schema_version is not compatible with this database "
            "(see docs/backup-snapshot-format.md): "
            f"{message}"
        )


class SnapshotIntegrityError(SnapshotError):
    """Checksum, member list, or structural validation failed."""

    def __init__(self, message: str):
        super().__init__(
            "Snapshot integrity failed (manifest, SHA-256 checksum, or ZIP layout): "
            f"{message}"
        )


class SnapshotValidationError(SnapshotError):
    """Snapshot data failed business rules (e.g. unbalanced journal)."""

    def __init__(self, message: str):
        super().__init__(
            "Snapshot validation failed (business rules, in-archive relations, or journal balance): "
            f"{message}"
        )


class IncompleteSnapshotError(SnapshotError):
    """Required ZIP members or metadata fields are missing."""

    def __init__(self, message: str):
        super().__init__(f"Invalid snapshot (archive or metadata): {message}")
