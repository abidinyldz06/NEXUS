import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from nexus.hub import github_status as github

SHA = "a" * 40


class GithubStatusTests(TestCase):
    def test_fixed_repo_sha_checks_and_no_checks_unknown(self):
        prs = [{"number": 4, "title": "<script>veri</script>", "headRefOid": SHA,
                "statusCheckRollup": [{"conclusion": "SUCCESS"}]},
               {"number": 5, "title": "diğer", "headRefOid": SHA, "statusCheckRollup": []}]
        with patch.object(github, "_read", side_effect=[{"sha": SHA}, prs,
             [{"headSha": SHA, "databaseId": 12, "status": "completed", "conclusion": "success"}]]) as read:
            result = github.snapshot()
        self.assertTrue(result["available"])
        self.assertEqual("başarılı", result["items"][0]["checks"])
        self.assertEqual("bilinmiyor", result["items"][1]["checks"])
        self.assertEqual(SHA, result["main"])
        self.assertEqual(3, read.call_count)
        self.assertTrue(all("abidinyldz06/NEXUS" in str(call) for call in read.call_args_list))

    def test_missing_auth_timeout_and_mismatched_sha_are_not_success(self):
        with patch.object(github, "_read", side_effect=RuntimeError("private-secret-error")):
            result = github.snapshot()
        self.assertFalse(result["available"])
        self.assertNotIn("private-secret-error", str(result))
        with patch.object(github, "_read", side_effect=[{"sha": SHA}, [],
             [{"headSha": "b" * 40, "databaseId": 12}]]):
            self.assertFalse(github.snapshot()["available"])

    def test_skipped_and_pending_checks_are_never_green(self):
        for state in ("SKIPPED", "NEUTRAL", "IN_PROGRESS"):
            pr = {"number": 1, "title": "test", "headRefOid": SHA,
                  "statusCheckRollup": [{"conclusion": state}]}
            with patch.object(github, "_read", side_effect=[{"sha": SHA}, [pr], []]):
                result = github.snapshot()
            self.assertNotEqual("başarılı", result["items"][0]["checks"])

    def test_cli_uses_no_shell_and_bounds_time_without_mutation(self):
        with patch.object(github.shutil, "which", return_value="/trusted/gh"):
            with patch.object(github.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps({"sha": SHA}))) as run:
                self.assertEqual({"sha": SHA}, github._read(["api", "repos/" + github.REPO + "/commits/main"]))
        args, kwargs = run.call_args
        self.assertEqual("/trusted/gh", args[0][0])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(8, kwargs["timeout"])
        self.assertEqual("github.com", kwargs["env"]["GH_HOST"])
        self.assertNotIn("GH_DEBUG", kwargs["env"])
