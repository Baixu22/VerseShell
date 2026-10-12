"""Offline P0-2 controls: no endpoint calls or measured task/fixture writes."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import task_generate_v2 as generator
import run_task_plan as driver


class GenerationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {"plan": [], "generation_policy": {
            "cohort": "cross_family", "evaluated_model": "evaluated",
            "model_families": {"evaluated": "family-e", "author": "family-a",
                               "variant-1": "family-b", "variant-2": "family-c"},
            "family_evidence": "offline test declarations, not real model metadata",
        }}
        self.plan_path = self.root / "plan.json"
        self.out = self.root / "candidates"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.env = {"ACI_BENCH_MODEL": "evaluated", "ACI_BENCH_BASE_URL": "invalid://offline",
                    "ACI_BENCH_API_KEY": "offline-dummy"}

    def invoke(self, module, extra):
        argv = [module.__file__, "--plan", str(self.plan_path), "--out", str(self.out),
                "--variant-models", "variant-1,variant-2", *extra]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()),                 contextlib.redirect_stderr(io.StringIO()):
            return module.main()

    def test_explicit_author_is_required(self):
        with patch.object(generator, "load_env", return_value=self.env),                 patch.object(generator, "chat", side_effect=AssertionError("network forbidden")):
            with self.assertRaises(SystemExit) as error:
                self.invoke(generator, [])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(self.out.exists())

    def test_policy_negative_controls(self):
        for change in ("missing", "same-family", "unknown-family", "no-source", "wrong-cohort"):
            with self.subTest(change=change):
                plan = copy.deepcopy(self.plan)
                if change == "missing":
                    del plan["generation_policy"]
                elif change == "same-family":
                    plan["generation_policy"]["model_families"]["author"] = "family-e"
                elif change == "unknown-family":
                    del plan["generation_policy"]["model_families"]["variant-2"]
                elif change == "no-source":
                    plan["generation_policy"]["family_evidence"] = ""
                else:
                    plan["generation_policy"]["cohort"] = "same_family"
                self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
                for module in (generator, driver):
                    with patch.object(generator, "load_env", side_effect=AssertionError("no credentials")),                             patch.object(generator, "chat", side_effect=AssertionError("network forbidden")),                             patch.object(driver.subprocess, "run", side_effect=AssertionError("no child")):
                        with self.assertRaises(SystemExit) as error:
                            self.invoke(module, ["--model", "author"])
                        self.assertEqual(error.exception.code, 2)
                self.assertFalse(self.out.exists())

    def test_variant_and_alias_controls(self):
        for variants in (["author", "variant-1"], ["variant-1", "variant-1"], ["variant-1"]):
            with self.subTest(variants=variants), self.assertRaises(ValueError):
                generator.generation_policy(self.plan, "author", variants)
        plan = copy.deepcopy(self.plan)
        plan["generation_policy"]["model_families"]["variant-1"] = "family-e"
        with self.assertRaises(ValueError):
            generator.generation_policy(plan, "author", ["variant-1", "variant-2"])

    def test_same_family_control_is_explicit(self):
        plan = copy.deepcopy(self.plan)
        plan["generation_policy"]["cohort"] = "same_family"
        policy = generator.generation_policy(plan, "evaluated", ["variant-1", "variant-2"])
        self.assertEqual(policy["cohort"], "same_family")
        self.assertEqual(policy["author_model"], "evaluated")

    def test_actual_authors_and_resume_scope(self):
        self.plan["plan"] = [{"index": 1, "lang": "python", "topic": "increment", "tier": "small"}]
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        old = self.out / "old"
        old.mkdir(parents=True)
        (old / "task.json").write_text(json.dumps({"provenance": {"plan_index": 1}}), encoding="utf-8")
        calls = []

        def chat(messages, *, model, **kwargs):
            calls.append(model)
            system = messages[0]["content"]
            if system == generator.SPEC_SYSTEM:
                return json.dumps({"id": "offline_increment", "module": "increment", "func": "inc",
                                   "correct_behaviour": "add one", "wrong": "returns the input"})
            if system == generator.TESTS_SYSTEM:
                return "from increment import inc\n\ndef test_inc():\n    assert inc(1) == 2\n"
            if system == generator.BUG_SYSTEM:
                return "def inc(x):\n    return x\n"
            return "def inc(x):\n    return x + 1\n"

        with patch.object(generator, "ROOT", self.root),                 patch.object(generator, "load_env", return_value=self.env),                 patch.object(generator, "chat", side_effect=chat),                 patch.object(generator, "run_suite", side_effect=[(True, ""), (True, ""),
                                                                    (False, ""), (True, ""), (True, "")]):
            self.assertEqual(self.invoke(generator, ["--model", "author"]), 0)
        self.assertEqual(calls, ["author"] * 4 + ["variant-1", "variant-2"])
        prov = json.loads((self.out / "offline_increment" / "task.json").read_text(encoding="utf-8"))["provenance"]
        self.assertEqual(prov["generator"], "author")
        self.assertEqual([v["model"] for v in prov["variants"]], ["variant-1", "variant-2"])
        policy = generator.generation_policy(self.plan, "author", ["variant-1", "variant-2"])
        self.assertEqual(prov["generation_policy"], policy)
        adm = self.root / "admission.json"
        adm.write_text(json.dumps({"candidates": [{"candidate": "old", "admissible": True}]}), encoding="utf-8")
        self.assertEqual(driver.admitted_indices(self.plan, self.out, adm, policy)[0], set())
        adm.write_text(json.dumps({"candidates": [{"candidate": "offline_increment", "admissible": True}]}), encoding="utf-8")
        self.assertEqual(driver.admitted_indices(self.plan, self.out, adm, policy)[0], {1})

    def test_no_fallback_to_another_author(self):
        self.plan["plan"] = [{"index": 1, "lang": "python", "topic": "increment", "tier": "small"}]
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        with patch.object(generator, "ROOT", self.root),                 patch.object(generator, "load_env", return_value=self.env),                 patch.object(generator, "chat", return_value=None) as chat,                 patch.object(generator.time, "sleep"):
            self.assertEqual(self.invoke(generator, ["--model", "author"]), 0)
        self.assertEqual([c.kwargs["model"] for c in chat.call_args_list], ["author"] * 3)
        self.assertEqual(list(self.out.glob("*/task.json")), [])

    def test_driver_stops_on_rejected_generation(self):
        self.plan['plan']=[{'index':1,'lang':'python','topic':'increment','tier':'small'}]
        self.plan_path.write_text(json.dumps(self.plan),encoding='utf-8')
        with patch.object(driver.subprocess, "run") as run:
            run.return_value.returncode = 2
            self.assertEqual(self.invoke(driver, ["--model", "author"]), 2)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
