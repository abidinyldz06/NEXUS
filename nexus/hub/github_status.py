"""Explicit, read-only GitHub status for one fixed repository; never dispatch."""
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

REPO = "abidinyldz06/NEXUS"
BASE = "https://github.com/" + REPO


def _read(args):
    executable = shutil.which("gh")
    if not executable:
        raise ValueError("missing CLI")
    env = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1")
    env.pop("GH_DEBUG", None)
    result = subprocess.run([executable, *args], capture_output=True, text=True,
                            timeout=8, check=True, env=env, stdin=subprocess.DEVNULL)
    if len(result.stdout) > 262144:
        raise ValueError("oversized result")
    return json.loads(result.stdout)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("invalid commit")
    return value


def snapshot():
    now = datetime.now(UTC).isoformat()
    try:
        main = _sha(_read(["api", "repos/" + REPO + "/commits/main", "--jq", "{sha:.sha}"])["sha"])
        prs = _read(["pr", "list", "--repo", REPO, "--state", "open", "--limit", "10",
                     "--json", "number,title,headRefOid,statusCheckRollup"])
        runs = _read(["run", "list", "--repo", REPO, "--branch", "main", "--commit", main,
                      "--limit", "1", "--json", "databaseId,headSha,status,conclusion"])
        if not isinstance(prs, list) or len(prs) > 10 or not isinstance(runs, list) or len(runs) > 1:
            raise ValueError("invalid response")
        items = []
        for pr in prs:
            number = pr["number"]
            if type(number) is not int or number <= 0 or not isinstance(pr["title"], str):
                raise ValueError("invalid PR")
            checks = pr.get("statusCheckRollup")
            if checks is not None and not isinstance(checks, list):
                raise ValueError("invalid checks")
            checks = checks or []
            states = [check.get("conclusion") or check.get("state") or check.get("status")
                      for check in checks]
            state = "bilinmiyor" if not states else (
                "başarılı" if all(s == "SUCCESS" for s in states) else
                "başarısız" if any(s in {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"} for s in states)
                else "bekliyor / atlanan kontrol")
            items.append({"number": number, "title": pr["title"][:240],
                          "head": _sha(pr["headRefOid"]), "checks": state,
                          "url": BASE + "/pull/" + str(number)})
        run = {"status": "bilinmiyor", "conclusion": None}
        if runs:
            row = runs[0]
            if row["headSha"] != main or type(row["databaseId"]) is not int:
                raise ValueError("mismatched run")
            run = {"status": str(row["status"])[:40], "conclusion": str(row.get("conclusion") or "")[:40],
                   "url": BASE + "/actions/runs/" + str(row["databaseId"])}
        return {"available": True, "repo": REPO, "main": main, "main_run": run,
                "items": items, "limit": 10, "read_at": now, "read_only": True}
    except Exception:
        return {"available": False, "repo": REPO, "items": [], "read_at": now,
                "read_only": True, "reason": "GitHub okunamadı; mevcut gh erişimi, ağ veya süre sınırı kontrol edilmeli. Eski sonuç gösterilmiyor."}
