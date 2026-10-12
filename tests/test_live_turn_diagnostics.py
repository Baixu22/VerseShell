"""P0-1 controls for tools/live_turn_diagnostics.py.

Synthetic artifacts only; no endpoint is contacted and no live run is touched. The
negative controls exist because the failure this tool must not have is the quiet one:
reading a missing per-turn field as "no truncation", or dressing a completion-token
count up as reasoning volume.
"""
import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "bench" / "aci" / "runners"))
import live_turn_diagnostics as diag  # noqa: E402
import live_agent_loop as lal  # noqa: E402

LEGACY_ROW_KEYS = (
    "task_id", "condition", "prompt_profile", "model", "run_index", "success",
    "success_reason", "tool_calls", "observation_tokens", "elapsed_ms", "notes",
    "trajectory", "optional_verify", "verify_unavailable", "weight",
    "agent_declared_success", "llm_prompt_tokens", "llm_completion_tokens", "turns",
    "completion_truncated_turns", "last_error", "api_error", "harness_fault",
    "harness_crash",
)


def turn_record(*, turn=1, finish_reason="stop", completion_tokens=10, prompt_tokens=100,
                tool_call_count=1, reasoning_returned=False, reasoning_chars=None,
                content_chars=20, request_ms=100, completion_truncated=None,
                fields_missing=None, **extra):
    if completion_truncated is None:
        completion_truncated = finish_reason == "length"
    record = {
        "turn": turn,
        "finish_reason": finish_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_returned": reasoning_returned,
        "reasoning_chars": reasoning_chars,
        "reasoning_keys": ["reasoning_content"] if reasoning_returned else [],
        "content_chars": content_chars,
        "tool_call_count": tool_call_count,
        "completion_truncated": completion_truncated,
        "request_ms": request_ms,
        "fields_missing": list(fields_missing if fields_missing is not None else (
            [] if reasoning_returned else ["reasoning_content (not returned by the endpoint)"])),
    }
    record.update(extra)
    return record


def row(*, turn_diagnostics=None, condition="verseshell_aci", task_id="synthetic-task",
        run_index=0, turns=1, completion_truncated_turns=0, llm_completion_tokens=0,
        success=False, **extra):
    payload = {
        "task_id": task_id,
        "condition": condition,
        "prompt_profile": "shell_neutral",
        "model": "synthetic-model",
        "run_index": run_index,
        "success": success,
        "tool_calls": 0,
        "observation_tokens": 0,
        "elapsed_ms": 1000,
        "notes": ["synthetic"],
        "trajectory": [],
        "llm_prompt_tokens": 100,
        "llm_completion_tokens": llm_completion_tokens,
        "turns": turns,
        "completion_truncated_turns": completion_truncated_turns,
        "last_error": None,
        "api_error": False,
        "harness_fault": None,
        "harness_crash": False,
    }
    if turn_diagnostics is not None:
        payload["turn_diagnostics"] = turn_diagnostics
    payload.update(extra)
    return payload


class TurnDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def run_tool(self, rows, *, cap=16384, name="artifact.json", out_name="report.json"):
        source = self.directory / name
        payload = {
            "schema": "verseshell.aci_bench.results/v1",
            "mode": "live",
            "generated_at": "synthetic",
            "live_config": {"max_tokens": cap},
            "rows": rows,
        }
        source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        out = self.directory / out_name
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = diag.main(["--input", str(source), "--out", str(out)])
        report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        return code, report, stdout.getvalue(), stderr.getvalue()

    def cell(self, report, index=0):
        return report["cells"][index]

    # ── required behaviours ──

    def test_turn1_truncated_with_reasoning_is_reasoning_burn(self):
        rows = [row(turns=1, completion_truncated_turns=1, llm_completion_tokens=16384,
                    turn_diagnostics=[turn_record(
                        finish_reason="length", completion_tokens=16384, tool_call_count=0,
                        reasoning_returned=True, reasoning_chars=5123, content_chars=0)])]
        code, report, stdout, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_REASONING_BURN)
        self.assertIs(cell["recorded"], True)
        self.assertEqual(cell["evidence"]["cap_reached"], True)
        self.assertEqual(cell["evidence"]["first_turn"]["reasoning_chars"], 5123)
        self.assertEqual(report["per_condition"]["verseshell_aci"]["truncated_cells"], 1)
        self.assertEqual(len(report["truncated_cells"]), 1)
        burned = report["truncated_cells"][0]
        self.assertEqual(
            (burned["task_id"], burned["condition"], burned["run_index"]),
            ("synthetic-task", "verseshell_aci", 0))
        self.assertIn("reasoning_burn", stdout)

    def test_turn1_truncated_without_reasoning_field_is_insufficient(self):
        rows = [row(turns=1, completion_truncated_turns=1, llm_completion_tokens=16384,
                    turn_diagnostics=[turn_record(
                        finish_reason="length", completion_tokens=16384, tool_call_count=0,
                        reasoning_returned=False, reasoning_chars=None, content_chars=0)])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_BUDGET_BURN)
        self.assertNotEqual(cell["classification"], diag.CLASS_REASONING_BURN)
        self.assertNotEqual(cell["classification"], diag.CLASS_NO_TRUNCATION)
        self.assertIsNone(cell["evidence"]["first_turn"]["reasoning_chars"])
        self.assertTrue(any("reasoning_content" in m
                            for m in cell["evidence"]["fields_missing"]))
        self.assertIn("no reasoning evidence", cell["reason"])

    def test_complete_untruncated_cell_is_no_truncation(self):
        rows = [row(turns=2, completion_truncated_turns=0, llm_completion_tokens=170,
                    turn_diagnostics=[
                        turn_record(turn=1, finish_reason="tool_calls", tool_call_count=2,
                                    reasoning_returned=False),
                        turn_record(turn=2, finish_reason="stop", tool_call_count=0,
                                    reasoning_returned=True, reasoning_chars=40),
                    ])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        self.assertEqual(self.cell(report)["classification"], diag.CLASS_NO_TRUNCATION)
        self.assertEqual(report["truncated_cells"], [])
        self.assertEqual(report["per_condition"]["verseshell_aci"]["truncated_cells"], 0)
        self.assertEqual(report["per_condition"]["verseshell_aci"]["recorded_cells"], 1)

    def test_old_schema_artifact_is_field_missing_not_healthy(self):
        rows = [row(turns=1, completion_truncated_turns=0, success=True)]
        code, report, stdout, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_FIELD_MISSING)
        self.assertIs(cell["recorded"], False)
        self.assertIn("predates per-turn recording", cell["reason"])
        self.assertEqual(report["input"]["rows_with_turn_diagnostics"], 0)
        self.assertTrue(report["warnings"])
        self.assertIn("unknown_field_missing", stdout)

    # ── negative controls ──

    def test_incomplete_or_malformed_turn_coverage_is_not_healthy(self):
        for turns, records in (
            (2, [turn_record()]),
            (3, [turn_record(), turn_record(turn=3)]),
            (2, [turn_record(), turn_record()]),
            (1, [turn_record(), "malformed"]),
            (None, [turn_record()]),
        ):
            with self.subTest(turns=turns, records=records):
                cell = diag.classify_cell(row(turns=turns, turn_diagnostics=records))
                self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_INCOMPLETE)

    def test_console_identifies_same_task_from_different_seeds(self):
        rows = [row(seed=seed, source_run=f"with_seed{seed}.json",
                    turn_diagnostics=[turn_record(finish_reason="length", tool_call_count=0)])
                for seed in (42, 43)]
        code, _, stdout, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        for seed in (42, 43):
            self.assertIn(f"seed={seed} source_run=with_seed{seed}.json", stdout)

    def test_missing_field_is_never_called_no_truncation(self):
        rows = [
            row(task_id="looks-clean", completion_truncated_turns=0, success=True),
            row(task_id="looks-burned", completion_truncated_turns=1,
                llm_completion_tokens=16384),
        ]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        for cell in report["cells"]:
            self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_FIELD_MISSING)
        self.assertNotIn(diag.CLASS_NO_TRUNCATION,
                         [c["classification"] for c in report["cells"]])
        self.assertEqual(report["per_condition"]["verseshell_aci"]["truncated_cells"], 0)
        self.assertEqual(report["per_condition"]["verseshell_aci"]["unknown_cells"], 2)

    def test_row_truncation_total_disagreeing_with_per_turn_records_is_not_healthy(self):
        """The row's own counter is independent evidence; a gap must not read as clean.

        The runner writes `completion_truncated_turns` from `finish_reason == "length"`
        on the same turns it records, so the two can only disagree when the per-turn
        list is incomplete or corrupt. Reporting `no_truncation` then would be exactly
        the quiet failure this tool exists to prevent (r15 verification finding F9).
        """
        for counter in (1, 2):
            with self.subTest(completion_truncated_turns=counter):
                records = [turn_record(turn=1, finish_reason="tool_calls", tool_call_count=1),
                           turn_record(turn=2, finish_reason="stop", tool_call_count=0)]
                cell = diag.classify_cell(
                    row(turns=2, completion_truncated_turns=counter,
                        turn_diagnostics=records), 16384)
                self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_INCOMPLETE)
                self.assertNotEqual(cell["classification"], diag.CLASS_NO_TRUNCATION)
                self.assertIn(f"completion_truncated_turns={counter}", cell["reason"])

    def test_missing_row_truncation_total_is_not_healthy(self):
        """A row with per-turn records but no cell-level total is undecided."""
        records = [turn_record(turn=1, finish_reason="stop", tool_call_count=0)]
        cell_row = row(turns=1, turn_diagnostics=records)
        cell_row.pop("completion_truncated_turns")
        cell = diag.classify_cell(cell_row, 16384)
        self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_INCOMPLETE)
        self.assertNotEqual(cell["classification"], diag.CLASS_NO_TRUNCATION)
        self.assertIn("does not record a cell-level", cell["reason"])

    def test_report_counts_row_counter_gap_as_unknown_not_truncated(self):
        """A gap is reported unknown: it is neither a truncation nor a clean cell."""
        rows = [
            row(task_id="gap", turns=2, completion_truncated_turns=1,
                turn_diagnostics=[
                    turn_record(turn=1, finish_reason="tool_calls", tool_call_count=1),
                    turn_record(turn=2, finish_reason="stop", tool_call_count=0),
                ]),
            row(task_id="clean", turns=1, completion_truncated_turns=0,
                turn_diagnostics=[turn_record(finish_reason="stop", tool_call_count=0)]),
        ]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        bucket = report["per_condition"]["verseshell_aci"]
        self.assertEqual(bucket["classification_counts"][diag.CLASS_UNKNOWN_INCOMPLETE], 1)
        self.assertEqual(bucket["classification_counts"][diag.CLASS_NO_TRUNCATION], 1)
        self.assertEqual(bucket["truncated_cells"], 0)
        self.assertEqual(bucket["unknown_cells"], 1)
        self.assertEqual(report["input"]["rows_with_turn_diagnostics"], 2)

    def test_reasoning_is_never_inferred_from_completion_tokens(self):
        burned = turn_record(finish_reason="length", completion_tokens=16381,
                             tool_call_count=0, content_chars=0)
        burned.pop("reasoning_returned")
        burned.pop("reasoning_chars")
        rows = [row(turns=1, completion_truncated_turns=1, llm_completion_tokens=16381,
                    turn_diagnostics=[burned])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_BUDGET_BURN)
        self.assertNotEqual(cell["classification"], diag.CLASS_REASONING_BURN)
        self.assertIsNone(cell["evidence"]["first_turn"].get("reasoning_chars"))
        self.assertIsNone(report["truncated_cells"][0]["reasoning_chars"])
        self.assertIs(report["truncated_cells"][0]["reasoning_returned"], None)

    def test_empty_reasoning_text_is_not_reasoning_evidence(self):
        rows = [row(turns=1, completion_truncated_turns=1, llm_completion_tokens=16384,
                    turn_diagnostics=[turn_record(
                        finish_reason="length", completion_tokens=16384, tool_call_count=0,
                        reasoning_returned=True, reasoning_chars=0, content_chars=0)])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        self.assertEqual(self.cell(report)["classification"], diag.CLASS_BUDGET_BURN)

    def test_later_turn_truncation_is_not_no_truncation(self):
        rows = [row(turns=2, completion_truncated_turns=1, llm_completion_tokens=16384,
                    turn_diagnostics=[
                        turn_record(turn=1, finish_reason="tool_calls", tool_call_count=1,
                                    completion_tokens=90, reasoning_returned=True,
                                    reasoning_chars=30),
                        turn_record(turn=2, finish_reason="length", tool_call_count=0,
                                    completion_tokens=16384),
                    ])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_TRUNCATED_OTHER)
        self.assertNotEqual(cell["classification"], diag.CLASS_NO_TRUNCATION)
        self.assertEqual(cell["evidence"]["truncated_turn_numbers"], [2])
        self.assertEqual(report["per_condition"]["verseshell_aci"]["truncated_cells"], 1)

    def test_request_error_turn_is_unknown_not_healthy(self):
        rows = [row(turns=1, api_error=True, last_error="HTTP 502 synthetic",
                    turn_diagnostics=[{
                        "turn": 1,
                        "request_ms": 300000,
                        "request_error": "RuntimeError: HTTP 502: proxy timeout",
                        "fields_missing": ["finish_reason", "prompt_tokens",
                                           "completion_tokens", "reasoning_content (no response)",
                                           "content_chars", "tool_call_count",
                                           "completion_truncated"],
                    }])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        self.assertEqual(self.cell(report)["classification"], diag.CLASS_UNKNOWN_INCOMPLETE)

    def test_false_flag_without_finish_reason_is_unknown(self):
        broken = turn_record(finish_reason=None, completion_truncated=False,
                             tool_call_count=1)
        rows = [row(turns=1, turn_diagnostics=[broken])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        cell = self.cell(report)
        self.assertEqual(cell["classification"], diag.CLASS_UNKNOWN_INCOMPLETE)
        self.assertNotEqual(cell["classification"], diag.CLASS_NO_TRUNCATION)

    def test_empty_diagnostics_list_is_missing_not_healthy(self):
        rows = [row(turns=1, turn_diagnostics=[])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        self.assertEqual(self.cell(report)["classification"], diag.CLASS_UNKNOWN_FIELD_MISSING)
        self.assertIs(self.cell(report)["recorded"], False)

    # ── input protection ──

    def test_input_artifact_is_never_rewritten(self):
        rows = [row(turn_diagnostics=[turn_record()])]
        source = self.directory / "artifact.json"
        payload = {"schema": "verseshell.aci_bench.results/v1", "live_config": {"max_tokens": 16384},
                   "rows": rows}
        blob = json.dumps(payload, ensure_ascii=False)
        source.write_text(blob, encoding="utf-8")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        out = self.directory / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = diag.main(["--input", str(source), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(source.read_text(encoding="utf-8"), blob)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["input"]["sha256"], before)

    def test_refuses_out_equal_to_input(self):
        source = self.directory / "artifact.json"
        source.write_text(json.dumps({"schema": "x", "live_config": {}, "rows": []}),
                          encoding="utf-8")
        before = source.read_bytes()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = diag.main(["--input", str(source), "--out", str(source)])
        self.assertEqual(code, 2)
        self.assertIn("never rewrites", stderr.getvalue())
        self.assertEqual(source.read_bytes(), before)

    def test_missing_input_returns_one(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = diag.main(["--input", str(self.directory / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("not found", stderr.getvalue())

    def test_report_carries_limitations_and_does_not_copy_rows(self):
        rows = [row(turn_diagnostics=[turn_record()])]
        code, report, _, _ = self.run_tool(rows)
        self.assertEqual(code, 0)
        self.assertTrue(report["limitations"])
        self.assertNotIn("trajectory", report["cells"][0])
        # the classifier must not mutate the row it was handed
        frozen = row(turn_diagnostics=None)
        before = copy.deepcopy(frozen)
        diag.classify_cell(frozen, 16384)
        self.assertEqual(frozen, before)


class LiveLoopWriterTests(unittest.TestCase):
    """Part A controls: the writer emits the diagnostic surface and changes nothing else.

    `chat_completion`, `execute_shell_cmd` and `check_success` are monkeypatched, so no
    endpoint is contacted and no fixture or toolchain is required.
    """

    TASK = {
        "id": "synthetic-task",
        "workspace_fixture": "synthetic-fixture-does-not-exist",
        "prompt": "synthetic prompt",
        "success": {"type": "file_equals", "path": "out.txt", "equals": "x"},
    }

    def response(self, finish_reason, *, content=None, reasoning=None, tool_calls=None,
                 prompt_tokens=100, completion_tokens=10):
        message = {"content": content}
        if reasoning is not None:
            message["reasoning_content"] = reasoning
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        return {"choices": [{"finish_reason": finish_reason, "message": message}],
                "usage": {"prompt_tokens": prompt_tokens,
                          "completion_tokens": completion_tokens}}

    def command_call(self):
        return [{"id": "call_1", "type": "function",
                 "function": {"name": "run_command",
                              "arguments": json.dumps({"command": "echo hi"})}}]

    def run_loop(self, responses, *, condition="raw_shell", max_tokens=16384):
        requests = []

        def fake_completion(messages, tools, **kwargs):
            requests.append({
                "messages": copy.deepcopy(messages),
                "tools": copy.deepcopy(tools),
                "kwargs": dict(kwargs),
            })
            item = responses[min(len(requests) - 1, len(responses) - 1)]
            if isinstance(item, Exception):
                raise item
            return item

        with patch.object(lal, "chat_completion", side_effect=fake_completion), \
                patch.object(lal, "execute_shell_cmd", return_value="synthetic observation"), \
                patch.object(lal, "check_success", return_value=(True, "synthetic ok")):
            row = lal.run_agent_loop(self.TASK, condition, model="synthetic-model",
                                     api_key="offline", base_url="http://offline.invalid",
                                     max_tokens=max_tokens)
        return row, requests

    def test_writer_keeps_legacy_keys_and_records_each_turn(self):
        row, requests = self.run_loop([
            self.response("tool_calls", content=None, reasoning="think " * 10,
                          tool_calls=self.command_call(), prompt_tokens=120,
                          completion_tokens=30),
            self.response("length", content="", reasoning="x" * 50,
                          prompt_tokens=200, completion_tokens=16384),
        ])
        for key in LEGACY_ROW_KEYS:
            self.assertIn(key, row)
        self.assertEqual([t["turn"] for t in row["turn_diagnostics"]], [1, 2])
        self.assertEqual(row["completion_truncated_turns"], 1)
        first, second = row["turn_diagnostics"]
        self.assertEqual(first["finish_reason"], "tool_calls")
        self.assertEqual((first["prompt_tokens"], first["completion_tokens"]), (120, 30))
        self.assertIs(first["reasoning_returned"], True)
        self.assertEqual(first["reasoning_chars"], len("think ") * 10)
        self.assertEqual(first["tool_call_count"], 1)
        self.assertIs(first["completion_truncated"], False)
        self.assertEqual(first["fields_missing"], [])
        self.assertIsInstance(first["request_ms"], int)
        self.assertEqual(second["finish_reason"], "length")
        self.assertEqual(second["completion_tokens"], 16384)
        self.assertIs(second["completion_truncated"], True)
        self.assertEqual(second["tool_call_count"], 0)
        # the analyzer reads the writer's row unchanged
        self.assertEqual(diag.classify_cell(row, 16384)["classification"],
                         diag.CLASS_TRUNCATED_OTHER)

    def test_writer_never_echoes_reasoning_or_diagnostics_into_the_messages(self):
        _, requests = self.run_loop([
            self.response("tool_calls", content=None, reasoning="secret reasoning",
                          tool_calls=self.command_call()),
            self.response("stop", content="done"),
        ])
        self.assertEqual(len(requests), 2)
        for request in requests:
            for message in request["messages"]:
                self.assertNotIn("reasoning_content", message)
                self.assertNotIn("turn_diagnostics", message)
        first_request = requests[0]["messages"]
        self.assertEqual(set(first_request[0]), {"role", "content"})
        self.assertEqual(first_request[0]["role"], "system")
        second_request = requests[1]["messages"]
        self.assertEqual(len(second_request), 4)
        self.assertEqual(second_request[1], {"role": "user", "content": "Begin the task."})
        self.assertEqual(second_request[2]["role"], "assistant")
        self.assertEqual(set(second_request[2]), {"role", "content", "tool_calls"})
        self.assertEqual(second_request[3], {"role": "tool", "tool_call_id": "call_1",
                                             "content": "synthetic observation"})
        # the request surface itself is unchanged by the recording
        self.assertEqual(requests[0]["tools"], requests[1]["tools"])
        self.assertEqual(requests[0]["tools"], lal.RAW_SHELL_TOOLS)
        self.assertEqual(requests[0]["kwargs"]["max_tokens"], 16384)
        self.assertEqual(requests[0]["kwargs"]["temperature"], 0.0)

    def test_writer_turn1_burn_is_classified_reasoning_burn(self):
        row, _ = self.run_loop([
            self.response("length", content="", reasoning="r" * 5000,
                          prompt_tokens=900, completion_tokens=16384),
        ])
        self.assertEqual(row["turns"], 1)
        self.assertEqual(row["completion_truncated_turns"], 1)
        self.assertIs(row["turn_diagnostics"][0]["completion_truncated"], True)
        cell = diag.classify_cell(row, 16384)
        self.assertEqual(cell["classification"], diag.CLASS_REASONING_BURN)
        self.assertIs(cell["evidence"]["cap_reached"], True)

    def test_writer_without_reasoning_field_records_absence_not_a_length(self):
        row, _ = self.run_loop([
            self.response("length", content="", reasoning=None,
                          prompt_tokens=900, completion_tokens=16384),
        ])
        turn = row["turn_diagnostics"][0]
        self.assertIs(turn["reasoning_returned"], False)
        self.assertIsNone(turn["reasoning_chars"])
        self.assertTrue(any("reasoning_content" in item for item in turn["fields_missing"]))
        self.assertEqual(diag.classify_cell(row, 16384)["classification"],
                         diag.CLASS_BUDGET_BURN)

    def test_writer_records_failed_request_and_analyzer_refuses(self):
        row, _ = self.run_loop([RuntimeError("HTTP 502 synthetic")])
        self.assertIs(row["api_error"], True)
        self.assertEqual(len(row["turn_diagnostics"]), 1)
        self.assertIn("502", row["turn_diagnostics"][0]["request_error"])
        self.assertEqual(diag.classify_cell(row, 16384)["classification"],
                         diag.CLASS_UNKNOWN_INCOMPLETE)

    def test_recording_bug_is_visible_in_the_row_and_never_fatal(self):
        store = []
        with patch.object(lal, "_turn_diagnostic", side_effect=RuntimeError("boom")):
            lal._record_turn_diagnostics(store, turn=3, finish_reason="stop",
                                         usage={}, msg={}, request_ms=1)
        self.assertEqual(len(store), 1)
        self.assertIn("boom", store[0]["record_error"])
        self.assertEqual(store[0]["turn"], 3)
        broken_row = row(turns=3, turn_diagnostics=store)
        self.assertEqual(diag.classify_cell(broken_row, 16384)["classification"],
                         diag.CLASS_UNKNOWN_INCOMPLETE)


if __name__ == "__main__":
    unittest.main()
