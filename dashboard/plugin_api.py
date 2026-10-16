"""Authenticated, read-only NEXUS Hub routes mounted by Hermes dashboard."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

_CORE_DIR = (Path(__file__).resolve().parents[1] / "nexus").resolve()
_CORE_NAME = "_hermes_nexus_hub_" + sha256(str(_CORE_DIR).encode()).hexdigest()[:12]
_CORE_SUFFIXES = (
    "config",
    "hub.service",
    "errors",
    "hub.tasks",
    "hub.routing",
    "hub.providers",
    "hub.pilot",
    "hub.budget",
    "hub.hermes_agents",
    "hub.github_status",
    "hub.operation_status",
)


def _drop_isolated_core(name: str = _CORE_NAME) -> None:
    """Remove one isolated package tree so a failed or stale load cannot linger."""
    prefix = name + "."
    for key in list(sys.modules):
        if key == name or key.startswith(prefix):
            sys.modules.pop(key, None)


def _load_isolated_core() -> dict[str, object]:
    """Load this checkout once under a path-stable name and reuse that cache."""
    init_file = _CORE_DIR / "__init__.py"
    cached = sys.modules.get(_CORE_NAME)
    cached_file = getattr(cached, "__file__", None)
    if cached is not None and (cached_file is None or Path(cached_file).resolve() != init_file):
        _drop_isolated_core()
        cached = None
    if cached is None:
        spec = importlib.util.spec_from_file_location(
            _CORE_NAME,
            init_file,
            submodule_search_locations=[str(_CORE_DIR)],
        )
        if spec is None or spec.loader is None:
            raise ImportError("NEXUS core package is unavailable")
        package = importlib.util.module_from_spec(spec)
        sys.modules[_CORE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except Exception:
            _drop_isolated_core()
            raise
    return {suffix: importlib.import_module(f"{_CORE_NAME}.{suffix}") for suffix in _CORE_SUFFIXES}


_core = _load_isolated_core()
_config_module = _core["config"]
_service = _core["hub.service"]
_errors = _core["errors"]
_tasks = _core["hub.tasks"]
_routing = _core["hub.routing"]
_providers = _core["hub.providers"]
_pilot = _core["hub.pilot"]
_budget = _core["hub.budget"]
_hermes_agents = _core["hub.hermes_agents"]
_github_status = _core["hub.github_status"]
_operation_status = _core["hub.operation_status"]

router = APIRouter()


class DraftRequest(BaseModel):
    idempotency_key: str
    title: str
    goal: str
    expected_output: str
    target_app: str
    data_class: str = "undetermined"
    hermes_session_id: str | None = None


class RouteAdviceRequest(BaseModel):
    request_text: str
    data_class: str = "undetermined"


class FreePilotRequest(BaseModel):
    request_id: str
    model: str

    model_config = ConfigDict(extra="forbid")


class SummaryRequest(FreePilotRequest):
    text: str
    external_authorized: StrictBool
    non_sensitive: StrictBool


class GenerationCostRequest(BaseModel):
    request_id: str
    generation_id: str | None = None
    evidence_confirmed: StrictBool = False

    model_config = ConfigDict(extra="forbid")


def _default_profile_only(request: Request) -> None:
    # _settings reads only the default Hermes plugin entry. Never write a draft
    # to that store while the dashboard is managing another profile.
    if request.query_params.get("profile") != "default":
        raise HTTPException(
            status_code=409,
            detail="görev taslakları bu profilde henüz desteklenmiyor",
        )


def _settings() -> Any:
    """Read the same namespaced values as PluginContext.get_config, without writes."""
    try:
        from hermes_cli.config import load_config_readonly

        raw = load_config_readonly() or {}
        entry = raw.get("plugins", {}).get("entries", {}).get("nexus", {})
        legacy = entry.get("config") if isinstance(entry, dict) else None
        current = entry.get("settings") if isinstance(entry, dict) else None
        values: dict[str, Any] = {}
        if isinstance(legacy, dict):
            values.update(legacy)
        if isinstance(current, dict):
            values.update(current)
        return _config_module.NexusConfig.from_mapping(values)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="NEXUS ayarları okunamadı") from exc


@router.get("/hub/overview")
def overview() -> dict[str, Any]:
    return _service.overview(_settings())


@router.get("/hub/hermes-agents")
def hermes_agents(request: Request) -> dict[str, Any]:
    _default_profile_only(request)
    return _hermes_agents.snapshot()


@router.get("/hub/github-status")
def github_status(request: Request) -> dict[str, Any]:
    _default_profile_only(request)
    return _github_status.snapshot()


@router.get("/hub/search")
def search(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    try:
        return _service.search(_settings(), q, limit=limit)
    except _errors.NexusIndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/hub/records/{record_id}")
def record(record_id: str) -> dict[str, Any]:
    try:
        return _service.record(_settings(), record_id)
    except _errors.NexusIndexError as exc:
        message = str(exc)
        status = 404 if "bulunamadı" in message else 409
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/hub/reviews")
def reviews(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    try:
        return _service.pending_reviews(_settings(), limit=limit)
    except _errors.ReviewStoreError as exc:
        raise HTTPException(status_code=503, detail="İnceleme kuyruğu okunamadı") from exc


@router.get("/hub/reviews/{review_id}")
def review(review_id: str) -> dict[str, Any]:
    try:
        return _service.review_detail(_settings(), review_id)
    except _errors.ReviewStoreError as exc:
        status = 404 if "bulunamadı" in str(exc) or "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail="İnceleme kaydı bulunamadı") from exc


@router.get("/hub/tasks")
def tasks(request: Request, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    _default_profile_only(request)
    try:
        return _tasks.list_drafts(_settings(), limit=limit)
    except _tasks.TaskDraftError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/hub/operation-status")
def operation_status(request: Request):
    _default_profile_only(request)
    try:
        return JSONResponse(_operation_status.snapshot(_settings()),
                            headers={"Cache-Control": "no-store"})
    except _budget.BudgetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/hub/route-advice")
def route_advice(request: Request, body: RouteAdviceRequest) -> dict[str, Any]:
    if request.query_params.get("profile") != "default":
        raise HTTPException(status_code=409, detail="yönlendirme bu profilde desteklenmiyor")
    try:
        return _routing.advise(body.request_text, data_class=body.data_class)
    except _routing.RouteAdviceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/hub/tasks")
def create_task(request: Request, draft: DraftRequest) -> dict[str, Any]:
    _default_profile_only(request)
    try:
        return _tasks.create_draft(
            _settings(),
            {
                "title": draft.title,
                "goal": draft.goal,
                "expected_output": draft.expected_output,
                "target_app": draft.target_app,
                "data_class": draft.data_class,
                "hermes_session_id": draft.hermes_session_id,
            },
            idempotency_key=draft.idempotency_key,
        )
    except _tasks.TaskDraftError as exc:
        status = 409 if "aynı işlem kimliği" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/hub/providers/{provider}/usage")
def provider_usage(request: Request, provider: str) -> dict[str, Any]:
    # Explicit action only; host supplies authentication and profile secret scope.
    if request.query_params.get("profile") != "default":
        raise HTTPException(status_code=409, detail="kullanım bu profilde desteklenmiyor")
    try:
        return _providers.snapshot(provider)
    except _providers.ProviderUsageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/hub/free-pilot")
def free_pilot(request: Request, body: FreePilotRequest) -> dict[str, Any]:
    if request.query_params.get("profile") != "default":
        raise HTTPException(status_code=409, detail="pilot yalnız default profilde destekleniyor")
    try:
        return _pilot.run(_settings(), request_id=body.request_id, model=body.model)
    except _budget.BudgetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=503, detail="pilot başlatılamadı; otomatik tekrar yok") from None


@router.post("/hub/generation-cost")
def generation_cost(request: Request, body: GenerationCostRequest) -> JSONResponse:
    # Explicit action only. Does not start a model call or open another ledger.
    if request.query_params.get("profile") != "default":
        raise HTTPException(status_code=409, detail="maliyet doğrulama yalnız default profilde destekleniyor")
    try:
        result = _pilot.confirm_generation_cost(
            _settings(), request_id=body.request_id, generation_id=body.generation_id,
            evidence_confirmed=body.evidence_confirmed,
        )
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except _budget.BudgetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=503, detail="maliyet doğrulanamadı; otomatik tekrar yok") from None


@router.post("/hub/selected-summary")
def selected_summary(request: Request, body: SummaryRequest) -> Any:
    if request.query_params.get("profile") != "default":
        raise HTTPException(status_code=409, detail="özet yalnız default profilde destekleniyor")
    try:
        result = _pilot.summarize(_settings(), **body.model_dump())
        return JSONResponse(result, headers={"Cache-Control": "no-store"})
    except _budget.BudgetError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=503, detail="özet sonucu doğrulanamadı; otomatik tekrar yok") from None
