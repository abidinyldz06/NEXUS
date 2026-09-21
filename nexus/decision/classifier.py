"""Optional classifier.dev adapter. Default-off; never logs source text."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from ..errors import DecisionError
from .categories import CLASSIFIER_LABELS, RouteCategory

_ALLOWED_BASENAME = "classify"


@dataclass(frozen=True, slots=True)
class ClassifierPrediction:
    category: RouteCategory
    confidence: float


def _parse_prediction(stdout: str) -> ClassifierPrediction:
    line = next((item.strip() for item in stdout.splitlines() if item.strip()), "")
    if not line:
        raise DecisionError("classifier returned no prediction")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise DecisionError("classifier output was not JSON") from exc
    if not isinstance(payload, dict):
        raise DecisionError("classifier output was not a JSON object")
    label = payload.get("label")
    confidence = payload.get("confidence")
    if label not in {item.value for item in CLASSIFIER_LABELS}:
        raise DecisionError("classifier returned an unsupported label")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise DecisionError("classifier returned an invalid confidence")
    return ClassifierPrediction(RouteCategory(label), float(confidence))


def predict_with_classifier(
    text: str,
    *,
    executable: str,
    timeout_seconds: float = 15,
    runner: Any = subprocess.run,
) -> ClassifierPrediction:
    """Classify via stdin JSON. The source text is never placed on argv."""
    if executable != _ALLOWED_BASENAME and not executable.startswith("/"):
        raise DecisionError("classifier executable must be 'classify' or an absolute path")
    if ".." in executable.split("/"):
        raise DecisionError("classifier executable path is unsafe")
    if runner is subprocess.run:
        resolved = shutil.which(executable) if executable == _ALLOWED_BASENAME else executable
        if resolved is None or not os.path.isfile(resolved) or os.path.islink(resolved):
            raise DecisionError("classifier executable is unavailable")
    else:
        resolved = executable
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"CLASSIFY_API_KEY"}
    }
    env["CLASSIFY_NO_PROGRESS"] = "1"
    env["CLASSIFY_NO_UPDATE_CHECK"] = "1"
    labels = ",".join(item.value for item in CLASSIFIER_LABELS)
    try:
        result = runner(
            [resolved, labels, "--json", "--field", "text"],
            input=json.dumps({"text": text}, ensure_ascii=False) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DecisionError("classifier invocation failed") from exc
    if result.returncode != 0:
        raise DecisionError("classifier invocation failed")
    return _parse_prediction(result.stdout)
