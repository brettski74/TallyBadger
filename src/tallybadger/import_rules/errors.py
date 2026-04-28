class ImportRulesError(ValueError):
    """Raised when rule configuration or evaluation cannot proceed (e.g. bad regex group ref)."""


class ImportRulesCelError(ImportRulesError):
    """Raised when CEL evaluation/configuration fails for a rule."""
