"""Real temporary Git histories; no remote/API or production artifact writes."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import resolve_pr_merge_base as scope
from tools import check_run287_artifact_hygiene as guard


class ArtifactScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "Synthetic test")
        self.git("config", "user.email", "test@example.invalid")
        self.file("cloud_results/paper_runs/latest_regime.txt", "old\n")
        self.file("tools/source.py", "base\n")
        self.base = self.commit("initial")
        self.git("switch", "-q", "-c", "feature")
        self.file("tools/news.py", "feature\n")
        self.head = self.commit("PR source")
        self.git("switch", "-q", "master")
        self.file("cloud_results/paper_runs/latest_regime.txt", "upstream\n")
        self.actual = self.commit("upstream bot update")
        self.git("merge", "-q", "--no-ff", "feature", "-m", "synthetic PR merge")
    def tearDown(self):
        self.temp.cleanup()
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()
    def file(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    def commit(self, text):
        self.git("add", "--all")
        self.git("commit", "-qm", text)
        return self.git("rev-parse", "HEAD")
    def resolved(self, **kwargs):
        args = dict(event_base=self.base, event_head=self.head)
        args.update(kwargs)
        return scope.resolve_base(self.root, **args)
    def audit(self, base):
        return guard.evaluate_changes(guard._changed_paths(base, self.root), self.root)
    def test_stale_event_base_reproduces_upstream_false_positive(self):
        old = self.audit(self.base)
        self.assertEqual(old["status"], "BLOCKED_ARTIFACT_HYGIENE")
        self.assertEqual(old["violations"][0]["path"], "cloud_results/paper_runs/latest_regime.txt")
    def test_resolved_base_does_not_attribute_upstream_change_to_pr(self):
        self.assertEqual(self.resolved(), self.actual)
        result = self.audit(self.resolved())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual([x["path"] for x in result["files"]], ["tools/news.py"])
    def merge_pr_change(self, path, content):
        self.git("checkout", "-q", "-b", "unsafe_feature", self.head)
        self.file(path, content)
        self.head = self.commit("actual PR artifact change")
        self.git("checkout", "-q", "-b", "new_merge", self.actual)
        # When both base and PR modify the same tracked artifact, simulate
        # GitHub's already-resolved merge by explicitly keeping PR content.
        proc = subprocess.run(["git", "merge", "-q", "--no-ff", "unsafe_feature",
                               "-m", "synthetic merge with artifact"],
                              cwd=self.root, capture_output=True)
        if proc.returncode:
            self.file(path, content)
            self.git("add", "--", path)
            self.git("commit", "-qm", "resolved synthetic merge with artifact")
    def test_real_pr_runtime_addition_remains_blocked(self):
        self.merge_pr_change("cloud_results/new_runtime.txt", "unsafe artifact\n")
        result = self.audit(self.resolved())
        self.assertEqual(result["violations"][0]["code"], "NEW_RUNTIME_BLOB_IN_GIT")
    def test_real_pr_runtime_edit_remains_blocked(self):
        self.merge_pr_change("cloud_results/paper_runs/latest_regime.txt", "PR change\n")
        self.assertEqual(self.audit(self.resolved())["status"], "BLOCKED_ARTIFACT_HYGIENE")
    def test_large_code_blob_remains_blocked(self):
        self.merge_pr_change("tools/huge.py", "x" * (guard.MAX_BLOB_BYTES + 1))
        result = self.audit(self.resolved())
        self.assertIn("GIT_BLOB_TOO_LARGE", {r["code"] for r in result["violations"]})
    def test_wrong_pr_head_rejected(self):
        with self.assertRaises(scope.MergeScopeError): self.resolved(event_head=self.base)
    def test_unrelated_base_rejected(self):
        merge = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "--orphan", "other")
        unrelated = self.commit("unrelated root")
        self.git("checkout", "-q", merge)
        with self.assertRaises(scope.MergeScopeError): self.resolved(event_base=unrelated)
    def test_non_merge_checkout_rejected(self):
        self.git("checkout", "-q", self.head)
        with self.assertRaises(scope.MergeScopeError): self.resolved()
    def test_short_or_injected_sha_rejected(self):
        for value in (self.base[:7], "HEAD", "--all", "bad; command", None):
            with self.subTest(value=value), self.assertRaises(scope.MergeScopeError):
                self.resolved(event_base=value)
    def test_existing_current_base_works(self):
        self.assertEqual(self.resolved(event_base=self.actual), self.actual)
    def test_resolution_is_read_only(self):
        head, status = self.git("rev-parse", "HEAD"), self.git("status", "--porcelain")
        self.resolved()
        self.assertEqual(head, self.git("rev-parse", "HEAD"))
        self.assertEqual(status, self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
