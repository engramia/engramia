"""Pipeline contract validation.

Each pipeline stage declares which workspace files it reads and writes.
A valid pipeline has no broken data-flow: every file a stage reads must
be either an initial input or produced by a prior stage's writes.

Also detects circular file dependencies across stages.
"""


def validate_contracts(stages: list[dict], initial_inputs: list[str] | None = None) -> list[str]:
    """Check that reads/writes form a consistent, acyclic chain.

    Args:
        stages: List of dicts, each with "reads" and "writes" keys
            (lists of filename strings). Ordered from first to last stage.
        initial_inputs: Files assumed to be available before any stage runs
            (e.g. the input files the user provides). Defaults to empty list.

    Returns:
        List of error strings. Empty list means the contract is valid.
    """
    available: set[str] = set(initial_inputs or [])
    errors: list[str] = []

    # Detect circular file dependencies:
    # A cycle occurs when a file written by stage N is also written by an
    # earlier stage AND later read back — i.e. a file appears in both
    # the writes of two different stages, creating ambiguity.
    # More precisely: if a stage reads a file that it also writes, that is
    # a self-cycle; if stage B writes a file that stage A (before B) wrote
    # and stage B also reads it, that is a re-write loop.
    written_by: dict[str, str] = {}  # filename → stage name that first wrote it

    for i, stage in enumerate(stages):
        reads: list[str] = stage.get("reads") or []
        writes: list[str] = stage.get("writes") or []
        name: str = stage.get("name") or stage.get("task") or f"stage_{i}"

        # Self-cycle: stage reads what it writes
        self_cycle = [f for f in reads if f in writes]
        if self_cycle:
            errors.append(
                f"Stage '{name}' has a self-cycle: it both reads and writes {self_cycle}."
            )

        missing = [f for f in reads if f not in available and f not in writes]
        if missing:
            errors.append(
                f"Stage '{name}' reads {missing} but these files are not produced by any prior stage."
            )

        # Cross-stage write conflict: detect if this stage overwrites a file
        # that a later stage will need to read from a different source.
        for f in writes:
            if f in written_by:
                errors.append(
                    f"Stage '{name}' writes '{f}' which was already written by stage '{written_by[f]}'. "
                    "This creates a circular or ambiguous data-flow."
                )
            else:
                written_by[f] = name

        available.update(writes)

    return errors


def infer_initial_inputs(task: str) -> list[str]:
    """Heuristically infer workspace input files from a task description.

    Looks for common file extensions and patterns in the task text.

    Args:
        task: High-level task description string.

    Returns:
        List of inferred input filenames (may be empty).
    """
    import re

    # Match explicit filenames (word.ext pattern)
    found = re.findall(r"\b\w+\.(?:csv|json|txt|xlsx?|parquet|yaml|toml|xml|html)\b", task, re.I)
    if found:
        return list(dict.fromkeys(found))  # deduplicate, preserve order

    # Fallback: common names based on keywords
    task_lower = task.lower()
    guesses: list[str] = []
    if "csv" in task_lower:
        guesses.append("sample.csv")
    if "json" in task_lower:
        guesses.append("sample.json")
    return guesses
