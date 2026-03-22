"""Pipeline contract validation.

Each pipeline stage declares which workspace files it reads and writes.
A valid pipeline has no broken data-flow: every file a stage reads must
be either an initial input or produced by a prior stage's writes.
"""


def validate_contracts(stages: list[dict], initial_inputs: list[str] | None = None) -> list[str]:
    """Check that reads/writes form a consistent chain.

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

    for i, stage in enumerate(stages):
        reads: list[str] = stage.get("reads") or []
        writes: list[str] = stage.get("writes") or []
        name: str = stage.get("name") or stage.get("task") or f"stage_{i}"

        missing = [f for f in reads if f not in available]
        if missing:
            errors.append(
                f"Stage '{name}' reads {missing} but these files are not produced by any prior stage."
            )

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
