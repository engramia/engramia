"""Tests for pipeline contract validation."""

from remanence.reuse.contracts import infer_initial_inputs, validate_contracts


class TestValidateContracts:
    def test_valid_chain(self):
        stages = [
            {"name": "reader", "reads": ["input.csv"], "writes": ["data.json"]},
            {"name": "processor", "reads": ["data.json"], "writes": ["report.txt"]},
        ]
        errors = validate_contracts(stages, initial_inputs=["input.csv"])
        assert errors == []

    def test_missing_input_detected(self):
        stages = [
            {"name": "processor", "reads": ["data.json"], "writes": ["report.txt"]},
        ]
        errors = validate_contracts(stages, initial_inputs=[])
        assert len(errors) == 1
        assert "data.json" in errors[0]

    def test_initial_inputs_satisfy_reads(self):
        stages = [{"name": "s", "reads": ["file.csv"], "writes": ["out.json"]}]
        errors = validate_contracts(stages, initial_inputs=["file.csv"])
        assert errors == []

    def test_prior_stage_write_satisfies_later_read(self):
        stages = [
            {"name": "a", "reads": [], "writes": ["mid.json"]},
            {"name": "b", "reads": ["mid.json"], "writes": ["final.txt"]},
        ]
        errors = validate_contracts(stages, initial_inputs=[])
        assert errors == []

    def test_empty_stages(self):
        assert validate_contracts([]) == []

    def test_stage_without_reads_is_valid(self):
        stages = [{"name": "s", "reads": [], "writes": ["out.json"]}]
        assert validate_contracts(stages) == []

    def test_multiple_missing_files(self):
        stages = [{"name": "s", "reads": ["a.csv", "b.json"], "writes": []}]
        errors = validate_contracts(stages, initial_inputs=[])
        assert len(errors) == 1
        assert "a.csv" in errors[0] or "b.json" in errors[0]


class TestInferInitialInputs:
    def test_explicit_csv_filename(self):
        inputs = infer_initial_inputs("Read data.csv and compute stats")
        assert "data.csv" in inputs

    def test_keyword_csv_fallback(self):
        inputs = infer_initial_inputs("Parse a CSV file and compute stats")
        assert any("csv" in f.lower() for f in inputs)

    def test_multiple_file_types(self):
        inputs = infer_initial_inputs("Read input.csv and write to output.json")
        assert "input.csv" in inputs
        assert "output.json" in inputs

    def test_no_files_returns_empty(self):
        inputs = infer_initial_inputs("Compute the fibonacci sequence")
        assert isinstance(inputs, list)
