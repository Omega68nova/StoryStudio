from __future__ import annotations

import json
import hashlib
import secrets
import asyncio
import re
from contextvars import ContextVar
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Database, decode_json_fields, new_id, utc_now
from app.schemas import (
    BibleUpdate,
    AbilityDefinitionCreate,
    EffectDefinitionCreate,
    ApplyEffectRequest,
    AbilityUseRequest,
    ImageGenerateRequest,
    SceneImageRequest,
    ImageSuggestionUpdate,
    PlanningDraftUpdate,
    PlanningApprovalRequest,
    PlanningBatchAcceptRequest,
    PlanningDeleteRequest,
    PlanningGenerateRequest,
    GenerationTaskGenerateRequest,
    GenerationTaskReviewRequest,
    GenerationTaskRejectRequest,
    GenerationResultUpdate,
    GenerationPlanTaskCreate,
    GenerationPlanTaskUpdate,
    GenerationDependenciesUpdate,
    PlanningSessionCreate,
    RandomPlanningDirectionRequest,
    PlanningImagePlanUpdate,
    PlanningImageGenerateBatch,
    ProjectStoryDefaultsUpdate,
    ProjectCreate,
    ProjectUpdate,
    ProjectMusicUpdate,
    MusicPlaybackUpdate,
    ReviewDecision,
    RuntimeSettingsUpdate,
    StatDefinitionCreate,
    StatAdjustmentRequest,
    StoryEditCreate,
    StoryRegenerateRequest,
    StoryTextUpdate,
    StoryTurnCreate,
    StorySettingsUpdate,
    WorldEntityCreate,
    WorldEntityUpdate,
    WorldCloneRequest,
    HardDeleteConfirm,
    WorldHeadUpdate,
    WorldMutationBatch,
    NpcSettingsUpdate,
    OutfitCreate,
    EntityMediaCreate,
    MediaAssetUpdate,
    MusicThemeCreate,
    MusicTrackUpdate,
    WorkflowPresetCreate,
    WorkflowMappings,
    DataResetRequest,
    MinigameConfigUpdate,
    MinigameGroupUpdate,
    MinigameResolveRequest,
    BulletHellCloneRequest,
    BulletHellSkillUpdate,
    BulletHellModeUpdate,
    BulletHellAttackUpdate,
    ProjectBulletHellUpdate,
    LoginRequest,
    PasswordChangeRequest,
    AdminUserCreate,
    AdminUserUpdate,
    AdminPasswordReset,
    ProjectAssignmentsUpdate,
    EnvironmentSettingsUpdate, WeatherDefinitionUpdate, WeatherTransitionsUpdate, TimePhasesUpdate, TimePhaseItem, TimePhaseOrderUpdate,
    AmbientPreferenceUpdate, AmbientVariantCreate, AmbientAssignmentCreate, AmbientSoundSetsUpdate, WeatherProposalDecision,
    NoisePreferenceUpdate, NoiseVariantUpdate,
    SceneEnvironmentUpdate,
    LocationBackgroundCreate, EnvironmentLocationUpdate, WorldRootUpdate, WorldRootCreate,
    MapAnchorUpdate, BarrierUpdate, TravelConnectionUpdate, EncounterRuleUpdate,
    TravelActionRequest,
    GeometryEditRequest, MapDiscoveryUpdate,
)
from app.services.events import EventHub
from app.services.runtimes import ComfyClient, LlamaClient, ProcessSupervisor
from app.services.memory import provider_for
from app.services.media import MediaValidationError, content_hash, store_media, validate_audio, validate_image
from app.services.image_prompt import ImagePromptReferenceError, expand_image_prompt
from app.services.scheduler import GenerationScheduler, read_settings
from app.services.workflow import WorkflowValidationError, normalize_workflow_graph, prune_workflow_graph, validate_workflow
from app.services.world import WorldValidationError
from app.services.worldClone import WorldCloneService
from app.services.lifecycle import DataLifecycle, LifecycleConflict, TERMINAL_JOB_STATUSES
from app.services.auth import AuthError, AuthService, AuthUser, COOKIE_NAME, SESSION_DAYS
from app.services.environment import EnvironmentService
from app.managers.soundManager import SoundManager
from app.data.dataProvider import DataProvider
from app.services.routeDataService import RouteDataService
from app.services.generationPlanApiService import GenerationPlanApiService
from app.services.batchGenerationApiService import BatchGenerationApiService
from app.services.batchGeneration import GenerationPlanError
from app.domain.adapters import outfit_from_record
from app.domain.world import Ability, EffectDefinition, RequirementExpression, Stat


db = Database()
events = EventHub()
supervisor = ProcessSupervisor()
scheduler = GenerationScheduler(db, events, supervisor)
lifecycle = DataLifecycle(db)
auth = AuthService(db)
environment = EnvironmentService(db)
data = DataProvider(db)
sound = SoundManager(db, events=events, data_provider=data)
route_data = RouteDataService(data)
generation_api = GenerationPlanApiService(db, data_provider=data, world=scheduler.world)
batch_api = BatchGenerationApiService(db, data_provider=data, world=scheduler.world)
world_clone = WorldCloneService(scheduler.world)
current_user_context: ContextVar[AuthUser | None] = ContextVar("current_user", default=None)
BUILD_VERSION = "0.17.0-environment"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="StoryStudio", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user() -> AuthUser:
    user = current_user_context.get()
    if not user:
        raise HTTPException(401, "Authentication required")
    return user


def _path_project_id(path: str) -> str | None:
    match = re.match(r"^/api/projects/([^/]+)", path)
    return match.group(1) if match else None


def _resource_project_id(path: str) -> str | None:
    """Resolve indirect member resources without trusting a client supplied project id."""
    lookups = (
        (r"^/api/bible/([^/]+)", "SELECT project_id FROM bible_documents WHERE id=?"),
        (r"^/api/story-nodes/([^/]+)", "SELECT project_id FROM story_nodes WHERE id=?"),
        (r"^/api/suggestions/([^/]+)", "SELECT n.project_id FROM image_suggestions s JOIN story_nodes n ON n.id=s.story_node_id WHERE s.id=?"),
        (r"^/api/minigames/sessions/([^/]+)", "SELECT project_id FROM minigame_sessions WHERE id=?"),
        (r"^/api/jobs/([^/]+)", "SELECT project_id FROM generation_jobs WHERE id=?"),
        (r"^/api/generation-plans/planning/([^/]+)", "SELECT project_id FROM generation_plans WHERE id=?"),
        (r"^/api/generation-plans/([^/]+)", "SELECT project_id FROM generation_plans WHERE id=?"),
        (r"^/api/entities/([^/]+)", "SELECT project_id FROM world_entities WHERE id=?"),
    )
    for pattern, query in lookups:
        match = re.match(pattern, path)
        if match:
            row = db.fetch_one(query, (match.group(1),))
            return row["project_id"] if row else None
    return None


def _member_route_allowed(method: str, path: str, user: AuthUser) -> bool:
    """Explicit member allowlist. Every unclassified route is denied."""
    if path in {"/api/health", "/api/version", "/api/auth/me", "/api/auth/logout", "/api/auth/password"}:
        return True
    if method == "GET" and path == "/api/projects":
        return True
    if path in {"/api/preferences/ambient", "/api/preferences/noises"} and method in {"GET", "PUT"}:
        return True
    direct_project = _path_project_id(path)
    if direct_project:
        allowed = (
            method == "GET" and re.fullmatch(r"/api/projects/[^/]+", path)
        ) or (
            method == "POST" and re.fullmatch(r"/api/projects/[^/]+/(turns|see)", path)
        ) or (
            method == "GET" and re.fullmatch(r"/api/projects/[^/]+/generation-plans", path)
        ) or (
            method == "POST" and re.fullmatch(r"/api/projects/[^/]+/generation-plans/random-direction", path)
        ) or (
            method == "GET" and re.fullmatch(r"/api/projects/[^/]+/(music|minigames/checkpoint)", path)
        ) or (
            method in {"GET", "PUT"} and re.fullmatch(r"/api/projects/[^/]+/music/playback", path)
        ) or (
            method == "GET" and re.fullmatch(r"/api/projects/[^/]+/environment/(scene|map)", path)
        ) or (
            method == "GET" and re.fullmatch(r"/api/projects/[^/]+/noises", path)
        ) or (
            method == "POST" and re.fullmatch(r"/api/projects/[^/]+/noises/[^/]+/play", path)
        )
        return bool(allowed and auth.assigned(user.id, direct_project))
    indirect_project = _resource_project_id(path)
    if indirect_project and auth.assigned(user.id, indirect_project):
        if path.startswith("/api/generation-plans/") and method in {"GET", "POST", "PUT"}:
            return True
        if method == "PATCH" and re.fullmatch(r"/api/bible/[^/]+", path):
            return True
        if method == "POST" and re.fullmatch(r"/api/minigames/sessions/[^/]+/(start|resolve|resume)", path):
            return True
        if method == "POST" and re.fullmatch(r"/api/story-nodes/[^/]+/regenerate", path):
            node_id = path.split("/")[3]
            node = db.fetch_one(
                "SELECT n.id,p.active_node_id FROM story_nodes n JOIN projects p ON p.id=n.project_id WHERE n.id=?",
                (node_id,),
            )
            return bool(node and node["active_node_id"] == node["id"])
        if method in {"GET", "PATCH"} and re.fullmatch(r"/api/suggestions/[^/]+", path):
            return True
        if method == "POST" and re.fullmatch(r"/api/suggestions/[^/]+/generate", path):
            return True
        if method == "GET" and re.fullmatch(r"/api/jobs/[^/]+", path):
            return True
        if method == "GET" and re.fullmatch(r"/api/entities/[^/]+/media", path):
            return True
        if method == "POST" and re.fullmatch(r"/api/jobs/[^/]+/cancel", path):
            job_id = path.split("/")[3]
            job = db.fetch_one("SELECT requested_by_user_id FROM generation_jobs WHERE id=?", (job_id,))
            return bool(job and job["requested_by_user_id"] == user.id)
    if method == "GET" and path in {"/api/minigames/manifests", "/api/music/themes", "/api/workflows", "/api/jobs"}:
        return True
    return False


def _member_media_allowed(path: str, user: AuthUser) -> bool:
    relative = path.removeprefix("/media/").replace("\\", "/")
    rows = db.fetch_all(
        "SELECT n.project_id FROM image_suggestions s JOIN story_nodes n ON n.id=s.story_node_id WHERE s.image_path=? "
        "UNION SELECT project_id FROM entity_media_assets WHERE file_path=? "
        "UNION SELECT pmt.project_id FROM music_tracks mt JOIN project_music_themes pmt ON pmt.theme_id=mt.theme_id WHERE mt.file_path=?",
        (relative, relative, relative),
    )
    return any(auth.assigned(user.id, row["project_id"]) for row in rows)


@app.middleware("http")
async def authenticated_boundary(request: Request, call_next):
    path = request.url.path
    if not (path.startswith("/api/") or path.startswith("/media/")):
        return await call_next(request)
    if path in {"/api/health", "/api/version", "/api/auth/login", "/api/auth/setup"}:
        return await call_next(request)
    if not auth.has_users():
        return Response(
            content=json.dumps({"detail": {"message": "Run bootstrap-admin.ps1 locally before signing in", "code": "setup_required"}}),
            status_code=503,
            media_type="application/json",
        )
    user = auth.user_for_token(request.cookies.get(COOKIE_NAME))
    if not user:
        return Response(content=json.dumps({"detail": "Authentication required"}), status_code=401, media_type="application/json")
    allowed = _member_media_allowed(path, user) if path.startswith("/media/") else _member_route_allowed(request.method, path, user)
    if not user.admin and not allowed:
        return Response(content=json.dumps({"detail": "This account is not allowed to perform that action"}), status_code=403, media_type="application/json")
    token = current_user_context.set(user)
    request.state.user = user
    try:
        return await call_next(request)
    finally:
        current_user_context.reset(token)


def require_project(project_id: str) -> dict[str, Any]:
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def require_node(node_id: str) -> dict[str, Any]:
    node = db.fetch_one("SELECT * FROM story_nodes WHERE id = ?", (node_id,))
    if not node:
        raise HTTPException(404, "Story node not found")
    return node


def require_idle_project(project_id: str) -> None:
    try:
        lifecycle.require_idle(project_id)
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc


def require_story_slot(project_id: str) -> None:
    active = db.fetch_one(
        "SELECT id FROM generation_jobs WHERE project_id=? AND kind='story' "
        "AND status IN ('queued','running','switching','awaiting_review','awaiting_minigame') LIMIT 1",
        (project_id,),
    )
    if active:
        raise HTTPException(409, {"message": "A story action is already active", "recovery_actions": ["cancel_active_action", "retry_after_completion"]})


async def require_comfy_for_image() -> ComfyClient:
    """Fast preflight before any image target is marked queued."""
    settings = read_settings(db)
    client = scheduler.comfy or ComfyClient(settings["comfy_url"])
    if not await client.health():
        raise HTTPException(503, {
            "message": "ComfyUI is not reachable. Start ComfyUI (or use Start runtimes in Settings), then try the image again.",
            "recovery_actions": ["start_comfyui", "validate_runtime_settings", "retry_image"],
        })
    scheduler.comfy = client
    return client


def clear_transient_guidance(story_node_id: str | None) -> None:
    if not story_node_id:
        return
    db.execute(
        "UPDATE generation_jobs SET payload_json=json_remove(payload_json,'$.guidance','$.replan_feedback') "
        "WHERE kind='story' AND status NOT IN ('queued','running','switching','awaiting_review') "
        "AND json_extract(result_json,'$.story_node_id')=? "
        "AND (json_extract(payload_json,'$.guidance') IS NOT NULL OR json_extract(payload_json,'$.replan_feedback') IS NOT NULL)",
        (story_node_id,),
    )


@app.get("/api/auth/setup")
async def auth_setup() -> dict[str, Any]:
    return {"ready": auth.has_users(), "bootstrap_command": "./bootstrap-admin.ps1"}


@app.post("/api/auth/login")
async def login(request: Request, credentials: LoginRequest, response: Response) -> dict[str, Any]:
    try:
        user, token = auth.authenticate(
            credentials.username,
            credentials.password,
            request.client.host if request.client else "unknown",
        )
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
    secure = request.url.scheme == "https" or forwarded == "https"
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return {"user": user}


@app.post("/api/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    auth.revoke_token(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/api/auth/me")
async def auth_me() -> dict[str, Any]:
    user = current_user()
    return {"user": {"id": user.id, "username": user.username, "role": user.role}, "permissions": {"admin": user.admin}}


@app.put("/api/auth/password", status_code=204)
async def change_own_password(request: PasswordChangeRequest, response: Response) -> Response:
    try:
        auth.change_password(current_user().id, request.current_password, request.new_password)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def require_admin() -> AuthUser:
    user = current_user()
    if not user.admin:
        raise HTTPException(403, "Administrator access required")
    return user


def _admin_count_excluding(user_id: str | None = None) -> int:
    if user_id:
        row = db.fetch_one("SELECT COUNT(*) count FROM users WHERE role='admin' AND enabled=1 AND id<>?", (user_id,))
    else:
        row = db.fetch_one("SELECT COUNT(*) count FROM users WHERE role='admin' AND enabled=1")
    return int((row or {}).get("count", 0))


@app.get("/api/admin/users")
async def admin_users() -> list[dict[str, Any]]:
    require_admin()
    rows = db.fetch_all("SELECT * FROM users ORDER BY username_normalized")
    for row in rows:
        row.update(auth.public_user(row))
        row.pop("password_hash", None)
        row.pop("username_normalized", None)
        row["project_ids"] = [
            item["project_id"] for item in db.fetch_all("SELECT project_id FROM user_project_access WHERE user_id=? ORDER BY project_id", (row["id"],))
        ]
    return rows


@app.post("/api/admin/users", status_code=201)
async def admin_create_user(request: AdminUserCreate) -> dict[str, Any]:
    require_admin()
    try:
        return auth.create_user(request.username, request.password, request.role)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(user_id: str, request: AdminUserUpdate) -> dict[str, Any]:
    actor = require_admin()
    target = db.fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not target:
        raise HTTPException(404, "User not found")
    removes_admin = target["role"] == "admin" and (
        request.role == "member" or request.enabled is False
    )
    if removes_admin and _admin_count_excluding(user_id) == 0:
        raise HTTPException(409, "The final enabled administrator cannot be disabled or demoted")
    if actor.id == user_id and request.enabled is False:
        raise HTTPException(409, "You cannot disable your current account")
    db.execute(
        "UPDATE users SET enabled=COALESCE(?,enabled), role=COALESCE(?,role), updated_at=? WHERE id=?",
        (None if request.enabled is None else int(request.enabled), request.role, utc_now(), user_id),
    )
    if request.enabled is False or (request.role is not None and request.role != target["role"]):
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
    return auth.public_user(db.fetch_one("SELECT * FROM users WHERE id=?", (user_id,)) or {})


@app.post("/api/admin/users/{user_id}/reset-password", status_code=204)
async def admin_reset_password(user_id: str, request: AdminPasswordReset, response: Response) -> Response:
    require_admin()
    if not db.fetch_one("SELECT 1 FROM users WHERE id=?", (user_id,)):
        raise HTTPException(404, "User not found")
    try:
        auth.set_password(user_id, request.password)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    return response


@app.put("/api/admin/users/{user_id}/projects")
async def admin_assign_projects(user_id: str, request: ProjectAssignmentsUpdate) -> dict[str, Any]:
    require_admin()
    if not db.fetch_one("SELECT 1 FROM users WHERE id=?", (user_id,)):
        raise HTTPException(404, "User not found")
    unique_ids = list(dict.fromkeys(request.project_ids))
    if unique_ids:
        placeholders = ",".join("?" for _ in unique_ids)
        found = db.fetch_all(f"SELECT id FROM projects WHERE id IN ({placeholders})", tuple(unique_ids))
        if len(found) != len(unique_ids):
            raise HTTPException(422, "One or more stories do not exist")
    with db.connect() as connection:
        connection.execute("DELETE FROM user_project_access WHERE user_id=?", (user_id,))
        connection.executemany(
            "INSERT INTO user_project_access(user_id,project_id,created_at) VALUES(?,?,?)",
            [(user_id, project_id, utc_now()) for project_id in unique_ids],
        )
    return {"user_id": user_id, "project_ids": unique_ids}


@app.delete("/api/admin/users/{user_id}", status_code=204)
async def admin_delete_user(user_id: str, response: Response) -> Response:
    actor = require_admin()
    target = db.fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not target:
        raise HTTPException(404, "User not found")
    if actor.id == user_id:
        raise HTTPException(409, "You cannot delete your current account")
    if target["role"] == "admin" and target["enabled"] and _admin_count_excluding(user_id) == 0:
        raise HTTPException(409, "The final enabled administrator cannot be deleted")
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/events")
async def websocket_events(socket: WebSocket) -> None:
    socket_token = socket.cookies.get(COOKIE_NAME)
    user = auth.user_for_token(socket_token)
    if not user:
        await socket.close(code=1008)
        return
    origin = socket.headers.get("origin")
    if origin:
        origin_host = urlparse(origin).netloc.casefold()
        accepted_hosts = {
            (socket.headers.get("host") or "").casefold(),
            (socket.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip().casefold(),
            "127.0.0.1:5173",
            "localhost:5173",
        }
        if origin_host not in accepted_hosts:
            await socket.close(code=1008)
            return
    await socket.accept()
    try:
        await socket.send_json({"type": "runtime", "payload": {"state": scheduler.state}})
        async for event in events.subscribe():
            refreshed_user = auth.user_for_token(socket_token)
            if not refreshed_user:
                await socket.close(code=1008)
                return
            user = refreshed_user
            if not user.admin:
                payload = event.get("payload") or {}
                project_id = payload.get("project_id") or (payload.get("node") or {}).get("project_id")
                job_id = payload.get("job_id")
                if not project_id and job_id:
                    job = db.fetch_one("SELECT project_id FROM generation_jobs WHERE id=?", (job_id,))
                    project_id = (job or {}).get("project_id")
                if not project_id or not auth.assigned(user.id, project_id):
                    continue
            await socket.send_json(event)
    except WebSocketDisconnect:
        return


@app.get("/api/projects")
async def list_projects() -> list[dict[str, Any]]:
    user = current_user()
    return route_data.list_projects(admin=user.admin, user_id=user.id)


@app.post("/api/projects", status_code=201)
async def create_project(request: ProjectCreate) -> dict[str, Any]:
    project = db.create_project(request.title.strip())
    environment.ensure_project(project["id"])
    db.execute("INSERT OR IGNORE INTO project_music_settings(project_id) VALUES (?)", (project["id"],))
    presets = {
        "adventure": [("hp", "HP", "character", 100, 0, 100), ("mana", "Mana", "character", 100, 0, 100)],
        "romance": [("favorability", "Favorability", "relationship", 0, -100, 100)],
    }
    for key, label, scope, default, minimum, maximum in presets.get(request.stats_preset, []):
        data.rules.save_stat(Stat(project_id=project["id"], stat_key=key, label=label, compatible_owner_kinds=[scope], default_value=default, minimum=minimum, maximum=maximum))
    return db.get_project(project["id"]) or project


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    user = current_user()
    project = require_project(project_id)
    project["bible_documents"] = db.fetch_all(
        "SELECT * FROM bible_documents WHERE project_id = ? ORDER BY position", (project_id,)
    )
    project["story_nodes"] = db.fetch_all(
        "SELECT * FROM story_nodes WHERE project_id = ? AND trashed = 0 ORDER BY created_at", (project_id,)
    )
    visible_story_ids = {node["id"] for node in db.story_path(project.get("active_node_id"))}
    if not user.admin:
        project["story_nodes"] = [node for node in project["story_nodes"] if node["id"] in visible_story_ids]
    project["trashed_story_nodes"] = [] if not user.admin else db.fetch_all(
        "SELECT * FROM story_nodes WHERE project_id = ? AND trashed = 1 ORDER BY created_at", (project_id,)
    )
    project["suggestions"] = db.fetch_all(
        "SELECT s.*,j.id image_job_id,j.status image_job_status,j.phase image_job_phase,"
        "j.progress_current image_progress_current,j.progress_total image_progress_total,j.progress_message image_progress_message "
        "FROM image_suggestions s JOIN story_nodes n ON n.id = s.story_node_id "
        "LEFT JOIN generation_jobs j ON j.id=(SELECT gj.id FROM generation_jobs gj "
        "WHERE json_extract(gj.payload_json,'$.suggestion_id')=s.id ORDER BY gj.created_at DESC LIMIT 1) "
        "WHERE n.project_id = ? AND n.trashed = 0 ORDER BY s.created_at",
        (project_id,),
    )
    if not user.admin:
        project["suggestions"] = [item for item in project["suggestions"] if item["story_node_id"] in visible_story_ids]
    interventions = db.fetch_all("SELECT i.* FROM npc_interventions i JOIN story_nodes n ON n.id = i.story_node_id WHERE n.project_id = ? AND n.trashed = 0 ORDER BY i.created_at", (project_id,))
    for item in interventions:
        item["cited_fact_ids"] = json.loads(item.pop("cited_fact_ids_json"))
    project["npc_interventions"] = interventions
    if not user.admin:
        project["npc_interventions"] = [item for item in interventions if item["story_node_id"] in visible_story_ids]
    project["scene_appearances"] = db.fetch_all("SELECT a.* FROM scene_appearances a JOIN story_nodes n ON n.id = a.story_node_id WHERE n.project_id = ? AND n.trashed = 0 ORDER BY a.created_at", (project_id,))
    if not user.admin:
        project["scene_appearances"] = [item for item in project["scene_appearances"] if item["story_node_id"] in visible_story_ids]
    project["story_settings"] = db.fetch_one(
        "SELECT default_generation_mode, response_max_tokens, ai_instructions FROM project_story_settings WHERE project_id=?", (project_id,)
    ) or {"default_generation_mode": "low", "response_max_tokens": 300, "ai_instructions": ""}
    if not user.admin:
        project["story_settings"].pop("ai_instructions", None)
    project["permissions"] = {
        "admin": user.admin,
        "edit_bible": True,
        "submit_story": True,
        "edit_story": user.admin,
        "manage_context": user.admin,
    }
    active_jobs = db.fetch_all(
        "SELECT id,kind,status,phase,progress_current,progress_total,progress_message,created_at,updated_at,"
        "requester_name_snapshot,requested_by_user_id,partial_output,payload_json FROM generation_jobs "
        "WHERE project_id=? AND status IN ('queued','running','switching','awaiting_review','awaiting_minigame') ORDER BY created_at",
        (project_id,),
    )
    for position, active_job in enumerate(active_jobs, start=1):
        payload = json.loads(active_job.pop("payload_json") or "{}")
        pending = payload.get("pending_action") or {}
        active_job["queue_position"] = position
        active_job["action_type"] = pending.get("action") or payload.get("action")
        active_job["input_preview"] = str(pending.get("content") or payload.get("guidance") or "")[:500]
        active_job["can_cancel"] = user.admin or active_job.get("requested_by_user_id") == user.id
    project["active_jobs"] = active_jobs
    active_minigame = db.fetch_one(
        "SELECT s.id FROM minigame_sessions s LEFT JOIN generation_jobs j ON j.id=s.job_id "
        "WHERE s.project_id=? AND s.status IN ('awaiting_input','resolved') AND s.parent_node_id IS ? ORDER BY s.created_at DESC LIMIT 1",
        (project_id, project.get("active_node_id")),
    )
    project["active_minigame"] = scheduler.minigames.get_session(active_minigame["id"]) if active_minigame else None
    historical = db.fetch_all("SELECT id FROM minigame_sessions WHERE project_id=? AND status='committed' ORDER BY created_at", (project_id,))
    ancestry = {node["id"] for node in db.story_path(project.get("active_node_id"))}
    project["minigame_sessions"] = []
    for row in historical:
        session = scheduler.minigames.get_session(row["id"])
        if session:
            session["active_on_branch"] = session.get("story_node_id") in ancestry
            if user.admin or session["active_on_branch"]:
                project["minigame_sessions"].append(session)
    return project


@app.get("/api/minigames/manifests")
async def minigame_manifests() -> list[dict[str, Any]]:
    return scheduler.minigames.manifests()


@app.get("/api/minigames/groups")
async def minigame_groups() -> list[dict[str, Any]]:
    return scheduler.minigames.groups()


@app.get("/api/bullethell/catalog")
async def bullethell_catalog() -> dict[str, Any]:
    return scheduler.minigames.bullethell.catalog()


@app.post("/api/bullethell/{kind}/{definition_id}/clone", status_code=201)
async def clone_bullethell_definition(kind: str, definition_id: str, request: BulletHellCloneRequest) -> dict[str, Any]:
    try:
        return scheduler.minigames.bullethell.clone(kind, definition_id, request.definition_key, request.name)
    except (WorldValidationError, Exception) as exc:
        if not isinstance(exc, WorldValidationError) and "UNIQUE" not in str(exc): raise
        raise HTTPException(422, str(exc)) from exc


@app.put("/api/bullethell/skills/{definition_id}")
async def update_bullethell_skill(definition_id: str, request: BulletHellSkillUpdate) -> dict[str, Any]:
    try: return scheduler.minigames.bullethell.update("skills", definition_id, request.model_dump())
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc


@app.put("/api/bullethell/modes/{definition_id}")
async def update_bullethell_mode(definition_id: str, request: BulletHellModeUpdate) -> dict[str, Any]:
    try: return scheduler.minigames.bullethell.update("modes", definition_id, request.model_dump())
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc


@app.put("/api/bullethell/attacks/{definition_id}")
async def update_bullethell_attack(definition_id: str, request: BulletHellAttackUpdate) -> dict[str, Any]:
    try: return scheduler.minigames.bullethell.update("attacks", definition_id, request.model_dump())
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc


@app.delete("/api/bullethell/{kind}/{definition_id}", status_code=204)
async def delete_bullethell_definition(kind: str, definition_id: str) -> None:
    try: scheduler.minigames.bullethell.delete(kind, definition_id)
    except WorldValidationError as exc: raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}/bullethell")
async def project_bullethell(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return scheduler.minigames.bullethell.project_settings(project_id)


@app.put("/api/projects/{project_id}/bullethell")
async def update_project_bullethell(project_id: str, request: ProjectBulletHellUpdate) -> dict[str, Any]:
    require_project(project_id)
    try: return scheduler.minigames.bullethell.update_project_settings(project_id, request.model_dump())
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc


@app.get("/api/projects/{project_id}/minigames")
async def project_minigames(project_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    return scheduler.minigames.configs(project_id)


@app.put("/api/projects/{project_id}/minigames/{game_key}")
async def update_project_minigame(project_id: str, game_key: str, request: MinigameConfigUpdate) -> dict[str, Any]:
    require_project(project_id)
    try:
        result = scheduler.minigames.update_config(project_id, game_key, request.model_dump())
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("minigame", {"project_id": project_id, "game_key": game_key, "configuration_changed": True})
    return result


@app.put("/api/projects/{project_id}/minigame-groups/{group_key}")
async def update_project_minigame_group(project_id: str, group_key: str, request: MinigameGroupUpdate) -> list[dict[str, Any]]:
    require_project(project_id)
    try:
        result = scheduler.minigames.set_group_enabled(project_id, group_key, request.enabled)
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("minigame", {"project_id": project_id, "group_key": group_key, "configuration_changed": True})
    return result


@app.get("/api/projects/{project_id}/minigames/checkpoint")
async def active_minigame_checkpoint(project_id: str) -> dict[str, Any] | None:
    project = require_project(project_id)
    row = db.fetch_one("SELECT id FROM minigame_sessions WHERE project_id=? AND status IN ('awaiting_input','resolved') AND parent_node_id IS ? ORDER BY created_at DESC LIMIT 1", (project_id, project.get("active_node_id")))
    return scheduler.minigames.get_session(row["id"]) if row else None


async def queue_minigame_continuation(session: dict[str, Any]) -> dict[str, Any]:
    job_id = session.get("job_id")
    if not job_id:
        raise HTTPException(409, {"message": "The original story operation was removed", "recovery_actions": ["retry_story"]})
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Story operation not found")
    if job["status"] in {"queued", "running"}:
        return job
    if session["status"] != "resolved":
        raise HTTPException(409, {"message": "Resolve the minigame before resuming", "recovery_actions": ["play_minigame"]})
    payload = dict(job["payload"])
    payload["minigame_session_id"] = session["id"]
    payload["minigame_session_ids"] = list(dict.fromkeys([*(payload.get("minigame_session_ids") or []), session["id"]]))
    db.update_job_payload(job_id, payload, "queued")
    await scheduler.enqueue(job_id)
    return db.get_job(job_id) or job


@app.post("/api/minigames/sessions/{session_id}/resolve")
async def resolve_minigame(session_id: str, request: MinigameResolveRequest) -> dict[str, Any]:
    try:
        session, changed = scheduler.minigames.resolve(session_id, request.model_dump(exclude_none=True))
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = await queue_minigame_continuation(session) if session["status"] == "resolved" else None
    if changed:
        await events.publish("minigame", {"project_id": session["project_id"], "session_id": session_id, "status": "resolved", "result": session["result"]})
    return {"session": scheduler.minigames.get_session(session_id), "job": job}


@app.post("/api/minigames/sessions/{session_id}/start")
async def start_minigame_attempt(session_id: str) -> dict[str, Any]:
    try:
        session, changed = scheduler.minigames.start_attempt(session_id)
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if changed:
        await events.publish("minigame", {
            "project_id": session["project_id"], "session_id": session_id, "status": "attempt_started",
        })
    return {"session": session, "changed": changed}


@app.post("/api/minigames/sessions/{session_id}/resume")
async def resume_minigame_story(session_id: str) -> dict[str, Any]:
    session = scheduler.minigames.get_session(session_id)
    if not session:
        raise HTTPException(404, "Minigame checkpoint not found")
    job = await queue_minigame_continuation(session)
    await events.publish("minigame", {"project_id": session["project_id"], "session_id": session_id, "status": "continuation_queued"})
    return job


@app.get("/api/projects/{project_id}/story-settings")
async def get_story_settings(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return db.fetch_one(
        "SELECT default_generation_mode, response_max_tokens, ai_instructions FROM project_story_settings WHERE project_id=?", (project_id,)
    ) or {"default_generation_mode": "low", "response_max_tokens": 300, "ai_instructions": ""}


@app.put("/api/projects/{project_id}/story-settings")
async def update_story_settings(project_id: str, request: StorySettingsUpdate) -> dict[str, Any]:
    require_project(project_id)
    db.execute(
        "INSERT INTO project_story_settings(project_id,default_generation_mode,response_max_tokens,ai_instructions,updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(project_id) DO UPDATE SET default_generation_mode=excluded.default_generation_mode, "
        "response_max_tokens=excluded.response_max_tokens,ai_instructions=excluded.ai_instructions,updated_at=excluded.updated_at",
        (project_id, request.default_generation_mode, request.response_max_tokens, request.ai_instructions.strip(), utc_now()),
    )
    return await get_story_settings(project_id)


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, request: ProjectUpdate) -> dict[str, Any]:
    require_project(project_id)
    db.execute(
        "UPDATE projects SET title = ?, updated_at = ? WHERE id = ?",
        (request.title.strip(), utc_now(), project_id),
    )
    return require_project(project_id)


@app.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(project_id: str) -> None:
    require_project(project_id)
    try:
        lifecycle.purge_project(project_id)
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc


@app.get("/api/projects/{project_id}/delete-impact")
async def project_delete_impact(project_id: str) -> dict[str, Any]:
    project = require_project(project_id)
    counts = {}
    for name, query in {
        "story_nodes": "SELECT COUNT(*) n FROM story_nodes WHERE project_id=?",
        "entities": "SELECT COUNT(*) n FROM world_entities WHERE project_id=?",
        "planning_sessions": "SELECT COUNT(*) n FROM generation_plans WHERE project_id=? AND source_kind='planning_workspace'",
        "jobs": "SELECT COUNT(*) n FROM generation_jobs WHERE project_id=?",
        "media": "SELECT COUNT(*) n FROM entity_media_assets WHERE project_id=?",
        "minigame_sessions": "SELECT COUNT(*) n FROM minigame_sessions WHERE project_id=?",
    }.items():
        counts[name] = int((db.fetch_one(query, (project_id,)) or {"n": 0})["n"])
    return {"project_id": project_id, "name": project["title"], "confirmation": project["title"], "counts": counts}


@app.delete("/api/projects/{project_id}/purge")
async def confirmed_project_purge(project_id: str, request: HardDeleteConfirm) -> dict[str, Any]:
    impact = await project_delete_impact(project_id)
    if request.confirmation != impact["confirmation"]:
        raise HTTPException(422, f"Type {impact['confirmation']} to confirm")
    try:
        result = lifecycle.purge_project(project_id)
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc
    return {"impact": impact, **result}


@app.patch("/api/bible/{document_id}")
async def update_bible(document_id: str, request: BibleUpdate) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM bible_documents WHERE id = ?", (document_id,)):
        raise HTTPException(404, "Story-bible document not found")
    db.execute(
        "UPDATE bible_documents SET title = ?, content = ?, updated_at = ? WHERE id = ?",
        (request.title.strip(), request.content, utc_now(), document_id),
    )
    return db.fetch_one("SELECT * FROM bible_documents WHERE id = ?", (document_id,)) or {}


@app.post("/api/projects/{project_id}/bible/clear")
async def clear_story_bible(project_id: str) -> dict[str, int]:
    require_project(project_id)
    require_idle_project(project_id)
    db.execute("UPDATE bible_documents SET content='', updated_at=? WHERE project_id=?", (utc_now(), project_id))
    return {"documents_cleared": 5}


def check_parent(project_id: str, parent_id: str | None) -> None:
    if parent_id:
        parent = require_node(parent_id)
        if parent["project_id"] != project_id:
            raise HTTPException(400, "Parent node belongs to another project")
        if parent.get("trashed"):
            raise HTTPException(409, "Restore the selected branch before continuing it")


@app.post("/api/projects/{project_id}/turns", status_code=202)
async def create_turn(project_id: str, request: StoryTurnCreate) -> dict[str, Any]:
    project = require_project(project_id)
    # Direct service-level tests and offline integrations do not pass through
    # HTTP middleware; they retain the historical local-administrator behavior.
    user = current_user_context.get() or AuthUser("", "Local administrator", "admin")
    parent_id = (request.parent_id if request.parent_id is not None else project.get("active_node_id")) if user.admin else project.get("active_node_id")
    check_parent(project_id, parent_id)
    inherited = db.fetch_one("SELECT pov_character_id, narration_mode FROM story_nodes WHERE id = ?", (parent_id,)) if parent_id else None
    if user.admin:
        pov_character_id = request.pov_character_id if request.pov_character_id is not None else (inherited or {}).get("pov_character_id")
        narration_mode = request.narration_mode or (inherited or {}).get("narration_mode") or "third_limited"
    else:
        pov_character_id = (inherited or {}).get("pov_character_id")
        narration_mode = (inherited or {}).get("narration_mode") or "third_limited"
    if pov_character_id:
        entity = scheduler.world.projection(project_id, parent_id)["entities"].get(pov_character_id)
        if not entity or entity["kind"] != "character":
            raise HTTPException(400, "POV character is not available on this branch")
    if request.requested_ability:
        try:
            actor_id = request.requested_ability.get("actor_id")
            actor = scheduler.world.projection(project_id, parent_id)["entities"].get(actor_id)
            if actor_id != pov_character_id or not actor or not actor.get("state", {}).get("player_controlled"):
                raise WorldValidationError("Requested abilities must belong to the selected player-controlled POV character")
            scheduler.world.normalize_mutations(project_id, parent_id, [{"tool": "useAbility", "arguments": request.requested_ability}], provenance="player")
        except WorldValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
    clear_transient_guidance(parent_id)
    story_settings = await get_story_settings(project_id)
    captured = {
        "generation_mode": request.generation_mode or story_settings["default_generation_mode"],
        "response_max_tokens": int(story_settings["response_max_tokens"]),
        "ai_instructions": story_settings.get("ai_instructions", ""),
    }
    if request.action in {"guide", "continue"}:
        payload: dict[str, Any] = {
            "parent_node_id": parent_id,
            "action": request.action,
            "pov_character_id": pov_character_id,
            "narration_mode": narration_mode,
            **captured,
        }
        if request.action == "guide":
            payload["guidance"] = request.content.strip()
        payload["requested_parent_id"] = parent_id
        payload["use_latest_head"] = not user.admin
        job = db.create_job(project_id, "story", payload, user.id or None, user.username)
        await scheduler.enqueue(job["id"])
        return {"user_node": None, "job": job}

    payload = {
        "pending_action": {
            "action": "manual_story" if request.action == "story" else request.action,
            "content": request.content.strip(),
        },
        "requested_parent_id": parent_id,
        "use_latest_head": not user.admin,
        "pov_character_id": pov_character_id,
        "narration_mode": narration_mode,
        **captured,
    }
    if request.requested_ability:
        payload["requested_ability"] = request.requested_ability
    job = db.create_job(project_id, "story", payload, user.id or None, user.username)
    await scheduler.enqueue(job["id"])
    return {"user_node": None, "job": job}


@app.post("/api/story-nodes/{node_id}/edit", status_code=202)
async def edit_turn(node_id: str, request: StoryEditCreate) -> dict[str, Any]:
    target = require_node(node_id)
    require_story_slot(target["project_id"])
    if target["role"] != "user":
        raise HTTPException(400, "Only user turns can be edited into a new branch")
    user_node = db.create_story_node(
        target["project_id"], target["parent_id"], "user", request.content.strip(),
        pov_character_id=target.get("pov_character_id"), narration_mode=target.get("narration_mode") or "third_limited",
        action_kind=target.get("action_kind") or "do",
    )
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (user_node["id"], utc_now(), target["project_id"]))
    settings = await get_story_settings(target["project_id"])
    job = db.create_job(target["project_id"], "story", {
        "user_node_id": user_node["id"], "generation_mode": settings["default_generation_mode"],
        "response_max_tokens": int(settings["response_max_tokens"]),
        "ai_instructions": settings.get("ai_instructions", ""),
    })
    await scheduler.enqueue(job["id"])
    return {"user_node": user_node, "job": job}


@app.patch("/api/story-nodes/{node_id}")
async def revise_story_text(node_id: str, request: StoryTextUpdate) -> dict[str, Any]:
    node = require_node(node_id)
    content = request.content.strip()
    revision_id, now = new_id(), utc_now()
    db.execute(
        "INSERT INTO story_node_revisions(id, story_node_id, previous_content, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (revision_id, node_id, node["content"], content, now),
    )
    db.execute("UPDATE story_nodes SET content = ? WHERE id = ?", (content, node_id))
    await events.publish("story", {"node_id": node_id, "edited": True, "memory_reconciled": False})
    return {"node": require_node(node_id), "revision_id": revision_id}


@app.get("/api/story-nodes/{node_id}/revisions")
async def story_text_revisions(node_id: str) -> list[dict[str, Any]]:
    require_node(node_id)
    return db.fetch_all("SELECT * FROM story_node_revisions WHERE story_node_id = ? ORDER BY created_at DESC", (node_id,))


@app.post("/api/story-revisions/{revision_id}/revert")
async def revert_story_text(revision_id: str) -> dict[str, Any]:
    revision = db.fetch_one("SELECT * FROM story_node_revisions WHERE id = ?", (revision_id,))
    if not revision:
        raise HTTPException(404, "Story revision not found")
    return await revise_story_text(revision["story_node_id"], StoryTextUpdate(content=revision["previous_content"]))


@app.delete("/api/story-nodes/{node_id}", status_code=202)
async def trash_story_subtree(node_id: str) -> dict[str, Any]:
    node = require_node(node_id)
    require_idle_project(node["project_id"])
    project = require_project(node["project_id"])
    subtree = db.fetch_all(
        "WITH RECURSIVE descendants(id) AS (SELECT ? UNION ALL SELECT n.id FROM story_nodes n JOIN descendants d ON n.parent_id=d.id) SELECT id FROM descendants",
        (node_id,),
    )
    ids = {item["id"] for item in subtree}
    for item_id in ids:
        db.execute("UPDATE story_nodes SET trashed = 1 WHERE id = ?", (item_id,))
    active = project.get("active_node_id")
    if active in ids:
        db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (node["parent_id"], utc_now(), node["project_id"]))
    await events.publish("world_head", {"project_id": node["project_id"], "node_id": node["parent_id"], "trashed": list(ids)})
    return {"trashed": list(ids), "node_id": node["parent_id"]}


@app.post("/api/story-nodes/{node_id}/restore")
async def restore_story_subtree(node_id: str) -> dict[str, Any]:
    node = require_node(node_id)
    require_idle_project(node["project_id"])
    subtree = db.fetch_all(
        "WITH RECURSIVE descendants(id) AS (SELECT ? UNION ALL SELECT n.id FROM story_nodes n JOIN descendants d ON n.parent_id=d.id) SELECT id FROM descendants",
        (node_id,),
    )
    for item in subtree:
        db.execute("UPDATE story_nodes SET trashed = 0 WHERE id = ?", (item["id"],))
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (node_id, utc_now(), node["project_id"]))
    await events.publish("story", {"node_id": node_id, "restored": True})
    return {"restored": [item["id"] for item in subtree]}


@app.get("/api/story-nodes/{node_id}/purge-impact")
async def story_purge_impact(node_id: str) -> dict[str, Any]:
    require_node(node_id)
    ids = [item["id"] for item in db.fetch_all(
        "WITH RECURSIVE subtree(id) AS (SELECT ? UNION ALL SELECT n.id FROM story_nodes n JOIN subtree s ON n.parent_id=s.id) SELECT id FROM subtree", (node_id,)
    )]
    placeholders = ",".join("?" for _ in ids)
    suggestions = int((db.fetch_one(f"SELECT COUNT(*) n FROM image_suggestions WHERE story_node_id IN ({placeholders})", ids) or {"n": 0})["n"])
    revisions = int((db.fetch_one(f"SELECT COUNT(*) n FROM story_node_revisions WHERE story_node_id IN ({placeholders})", ids) or {"n": 0})["n"])
    return {"node_id": node_id, "confirmation": "PURGE STORY", "counts": {"nodes": len(ids), "suggestions": suggestions, "revisions": revisions}}


@app.delete("/api/story-nodes/{node_id}/purge")
async def purge_story_subtree(node_id: str, request: HardDeleteConfirm) -> dict[str, Any]:
    node = require_node(node_id)
    impact = await story_purge_impact(node_id)
    if not node.get("trashed"):
        raise HTTPException(409, {"message": "Move the story subtree to trash before purging it", "recovery_actions": ["trash_subtree"]})
    if request.confirmation != impact["confirmation"]:
        raise HTTPException(422, f"Type {impact['confirmation']} to confirm")
    try:
        lifecycle.require_idle(node["project_id"])
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc
    paths = [row["image_path"] for row in db.fetch_all(
        "WITH RECURSIVE subtree(id) AS (SELECT ? UNION ALL SELECT n.id FROM story_nodes n JOIN subtree s ON n.parent_id=s.id) "
        "SELECT image_path FROM image_suggestions WHERE story_node_id IN (SELECT id FROM subtree) AND image_path IS NOT NULL", (node_id,)
    )]
    db.execute("DELETE FROM story_nodes WHERE id=?", (node_id,))
    lifecycle.release_paths(paths)
    return impact


@app.delete("/api/story-nodes/{node_id}/revisions")
async def clear_story_revisions(node_id: str) -> dict[str, int]:
    node = require_node(node_id)
    require_idle_project(node["project_id"])
    count = int((db.fetch_one("SELECT COUNT(*) n FROM story_node_revisions WHERE story_node_id=?", (node_id,)) or {"n": 0})["n"])
    db.execute("DELETE FROM story_node_revisions WHERE story_node_id=?", (node_id,))
    return {"removed": count}


@app.post("/api/story-nodes/{node_id}/regenerate", status_code=202)
async def regenerate_turn(node_id: str, request: StoryRegenerateRequest | None = None) -> dict[str, Any]:
    target = require_node(node_id)
    require_story_slot(target["project_id"])
    previous = db.fetch_one(
        "SELECT payload_json,result_json FROM generation_jobs WHERE kind='story' AND json_extract(result_json,'$.story_node_id')=? "
        "ORDER BY created_at DESC LIMIT 1", (target["id"],),
    ) if target["role"] == "assistant" else None
    if previous:
        payload = json.loads(previous["payload_json"])
    else:
        user_node_id = target["parent_id"] if target["role"] == "assistant" else target["id"]
        if not user_node_id:
            raise HTTPException(400, "Assistant node has no source turn")
        payload = {"user_node_id": user_node_id}
    if request and request.guide.strip():
        payload["replan_feedback"] = request.guide.strip()
    settings = await get_story_settings(target["project_id"])
    payload.setdefault("generation_mode", settings["default_generation_mode"])
    payload.setdefault("response_max_tokens", int(settings["response_max_tokens"]))
    payload.setdefault("ai_instructions", settings.get("ai_instructions", ""))
    if request and request.generation_mode:
        payload["generation_mode"] = request.generation_mode
    preserved_sessions: list[dict[str, Any]] = []
    if previous and previous.get("result_json"):
        prior_result = json.loads(previous["result_json"])
        prior_ids = list(prior_result.get("minigame_session_ids") or [])
        if prior_result.get("minigame_session_id") and prior_result["minigame_session_id"] not in prior_ids:
            prior_ids.append(prior_result["minigame_session_id"])
        preserved_sessions = [session for session_id in prior_ids if (session := scheduler.minigames.get_session(session_id))]
    payload.pop("minigame_session_id", None)
    payload.pop("minigame_session_ids", None)
    payload.pop("retry_preserved_minigames", None)
    actor = current_user()
    job = db.create_job(target["project_id"], "story", payload, actor.id, actor.username)
    cloned_session_ids: list[str] = []
    preserved_inventory_costs = [
        mutation for mutation in (preserved_sessions[-1].get("staged_mutations", []) if preserved_sessions else [])
        if mutation.get("tool") == "adjustInventory"
    ]
    for index, preserved_session in enumerate(preserved_sessions):
        if not preserved_session.get("result"):
            continue
        session_id, now = new_id(), utc_now()
        db.execute(
            "INSERT INTO minigame_sessions(id,project_id,job_id,parent_node_id,game_key,game_version,status,invocation_json,result_json,partial_prose,staged_mutations_json,interventions_json,suggestion_json,continuation_count,created_at,resolved_at,updated_at) VALUES (?,?,?,?,?,?,'resolved',?,?,?,?,?,?,1,?,?,?)",
            (session_id, target["project_id"], job["id"], payload.get("user_node_id") or payload.get("parent_node_id"), preserved_session["game_key"], preserved_session["game_version"], json.dumps(preserved_session["invocation"]), json.dumps(preserved_session["result"]), "", json.dumps(preserved_inventory_costs if index == len(preserved_sessions) - 1 else []), "[]", None, now, now, now),
        )
        cloned_session_ids.append(session_id)
    if cloned_session_ids:
        payload["minigame_session_id"] = cloned_session_ids[-1]
        payload["minigame_session_ids"] = cloned_session_ids
        payload["retry_preserved_minigames"] = True
        db.update_job_payload(job["id"], payload, "queued")
    source_node_id = payload.get("user_node_id") or payload.get("parent_node_id")
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (source_node_id, utc_now(), target["project_id"]))
    await scheduler.enqueue(job["id"])
    return job


@app.put("/api/projects/{project_id}/head")
async def set_world_head(project_id: str, request: WorldHeadUpdate) -> dict[str, Any]:
    require_project(project_id)
    checkpoint_job = db.fetch_one(
        "SELECT job_id,parent_node_id FROM minigame_sessions WHERE project_id=? AND status IN ('awaiting_input','resolved') ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    if checkpoint_job and request.node_id != checkpoint_job["parent_node_id"] and checkpoint_job.get("job_id"):
        await scheduler.cancel(checkpoint_job["job_id"])
    if request.node_id:
        node = require_node(request.node_id)
        if node["project_id"] != project_id or node["status"] == "rejected" or node.get("trashed"):
            raise HTTPException(400, "The selected node is not an available branch head")
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (request.node_id, utc_now(), project_id))
    await events.publish("world_head", {"project_id": project_id, "node_id": request.node_id})
    return {"node_id": request.node_id, "projection": scheduler.world.projection(project_id, request.node_id, use_cache=False)}


@app.post("/api/projects/{project_id}/undo")
async def undo_world_head(project_id: str) -> dict[str, Any]:
    project = require_project(project_id)
    checkpoint_job = db.fetch_one(
        "SELECT job_id FROM minigame_sessions WHERE project_id=? AND status IN ('awaiting_input','resolved') ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    if checkpoint_job and checkpoint_job.get("job_id"):
        await scheduler.cancel(checkpoint_job["job_id"])
    path = db.story_path(project.get("active_node_id"))
    if not path:
        return {"node_id": None}
    remove_count = 2 if path[-1]["role"] == "assistant" and len(path) >= 2 and path[-2]["role"] == "user" else 1
    target = path[-remove_count - 1]["id"] if len(path) > remove_count else None
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (target, utc_now(), project_id))
    await events.publish("world_head", {"project_id": project_id, "node_id": target})
    return {"node_id": target, "redo_options": db.fetch_all("SELECT * FROM story_nodes WHERE parent_id IS ?", (target,))}


@app.post("/api/projects/{project_id}/redo")
async def redo_world_head(project_id: str) -> dict[str, Any]:
    project = require_project(project_id)
    current = project.get("active_node_id")
    children = db.fetch_all(
        "SELECT * FROM story_nodes WHERE project_id = ? AND parent_id IS ? AND status != 'rejected' AND trashed = 0 ORDER BY created_at DESC",
        (project_id, current),
    )
    if not children:
        return {"node_id": current, "redo_options": []}
    target = children[0]
    if target["role"] == "user":
        replies = db.fetch_all(
            "SELECT * FROM story_nodes WHERE project_id = ? AND parent_id = ? AND status != 'rejected' AND trashed = 0 ORDER BY created_at DESC",
            (project_id, target["id"]),
        )
        if replies:
            target = replies[0]
    db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (target["id"], utc_now(), project_id))
    await events.publish("world_head", {"project_id": project_id, "node_id": target["id"]})
    return {"node_id": target["id"], "redo_options": children}


@app.get("/api/projects/{project_id}/world")
async def get_world(project_id: str, head_node_id: str | None = None) -> dict[str, Any]:
    require_project(project_id)
    projection = scheduler.world.projection(project_id, head_node_id)
    projection["entities"] = {
        entity_id: {**entity, "card": scheduler.world.entity_card(project_id, entity_id, head_node_id)["card"],
                    "stats": scheduler.world.effective_stats(project_id, entity) if entity["kind"] == "character" else entity.get("stats", {})}
        for entity_id, entity in projection["entities"].items()
    }
    return projection


@app.get("/api/preferences/ambient")
async def get_ambient_preferences() -> dict[str, Any]:
    return environment.user_preferences(current_user().id)


@app.put("/api/preferences/ambient")
async def update_ambient_preferences(request: AmbientPreferenceUpdate) -> dict[str, Any]:
    user = current_user()
    db.execute(
        "INSERT INTO user_ambient_preferences(user_id,enabled,master_volume,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,master_volume=excluded.master_volume,updated_at=excluded.updated_at",
        (user.id, int(request.enabled), request.master_volume, utc_now()),
    )
    return environment.user_preferences(user.id)


@app.get("/api/preferences/noises")
async def get_noise_preferences() -> dict[str, Any]:
    return sound.noise_preferences(current_user().id)


@app.put("/api/preferences/noises")
async def update_noise_preferences(
    request: NoisePreferenceUpdate,
) -> dict[str, Any]:
    user = current_user()
    data.sound.set_noise_preferences(
        user.id,
        enabled=request.enabled,
        master_volume=request.master_volume,
    )
    return sound.noise_preferences(user.id)


@app.get("/api/projects/{project_id}/environment/scene")
async def get_scene_environment(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return environment.scene(project_id, scheduler.world.projection(project_id))


@app.get("/api/projects/{project_id}/environment/map")
async def get_environment_map(project_id: str, parent_id: str | None = None) -> dict[str, Any]:
    require_project(project_id)
    return environment.map_layer(project_id, scheduler.world.projection(project_id), parent_id, admin=current_user().admin)


def _commit_spatial_mutation(project_id: str, tool: str, arguments: dict[str, Any], summary: str) -> tuple[dict[str, Any], dict[str, Any]]:
    project = require_project(project_id)
    mutations = scheduler.world.normalize_mutations(
        project_id, project.get("active_node_id"),
        [{"tool": tool, "arguments": arguments}], provenance="author",
    )
    transaction = (
        scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary=summary)
        if project.get("active_node_id") else
        scheduler.world.commit_root(project_id, mutations, provenance="author", summary=summary)
    )
    return transaction, mutations[0].arguments


def _commit_spatial_mutations(project_id: str, raw: list[dict[str, Any]], summary: str) -> tuple[dict[str, Any], list[Any]]:
    project = require_project(project_id)
    mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), raw, provenance="author")
    transaction = (
        scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary=summary)
        if project.get("active_node_id") else
        scheduler.world.commit_root(project_id, mutations, provenance="author", summary=summary)
    )
    return transaction, mutations


@app.get("/api/projects/{project_id}/spatial/map")
async def get_spatial_map(project_id: str, location_id: str | None = None) -> dict[str, Any]:
    require_project(project_id)
    from app.services.spatial import SpatialService
    return SpatialService(scheduler.world.projection(project_id)).local_map(location_id, administrative=current_user().admin, include_geometry=current_user().admin)


@app.put("/api/projects/{project_id}/spatial/root")
async def set_spatial_root(project_id: str, request: WorldRootUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "setWorldRoot", request.model_dump(), "World root changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.post("/api/projects/{project_id}/spatial/root", status_code=201)
async def create_spatial_root(project_id: str, request: WorldRootCreate) -> dict[str, Any]:
    root_id = new_id()
    raw = [
        {"tool": "createEntity", "arguments": {"entity_id": root_id, "kind": "location", "name": request.name, "state": {
            "topology": request.topology, "occupancy": request.occupancy, "boundary_access": "free", "spatial_kind": "area",
            "minutes_per_unit": request.minutes_per_unit, "enabled": True, "discovered": True, "exposure": "outdoor",
        }}},
        {"tool": "setWorldRoot", "arguments": {"root_location_id": root_id, "reparent_previous": request.extend_scope, "adopt_top_level": request.extend_scope}},
    ]
    try:
        transaction, _ = _commit_spatial_mutations(project_id, raw, "World scope extended" if request.extend_scope else "World root created")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return scheduler.world.entity_card(project_id, root_id)


@app.post("/api/projects/{project_id}/spatial/migrate")
async def migrate_legacy_spatial_map(project_id: str) -> dict[str, Any]:
    projection = scheduler.world.projection(project_id)
    if projection.get("root_location_id"):
        return {"changed": False, "root_location_id": projection["root_location_id"]}
    top_level = [item for item in projection["entities"].values() if item.get("kind") == "location" and not item.get("state", {}).get("archived") and not item.get("state", {}).get("parent_location_id")]
    if not top_level:
        return {"changed": False, "root_location_id": None, "spatial_enabled": False}
    root_id = top_level[0]["id"] if len(top_level) == 1 else new_id()
    raw = []
    if len(top_level) > 1:
        raw.append({"tool": "createEntity", "arguments": {"entity_id": root_id, "kind": "location", "name": "World", "state": {"topology": "closed", "occupancy": "child_required", "boundary_access": "free", "spatial_kind": "area", "enabled": True, "discovered": True, "exposure": "outdoor"}}})
    for location in projection["entities"].values():
        state = location.get("state", {})
        if location.get("kind") != "location" or state.get("footprint") or state.get("x") is None or state.get("y") is None:
            continue
        coordinate_space = state.get("parent_location_id") or (root_id if location["id"] != root_id else location["id"])
        raw.append({"tool": "updateEntity", "arguments": {"entity_id": location["id"], "patch": {"footprint": {"location_id": coordinate_space, "kind": "point", "points": [{"x": state["x"], "y": state["y"]}]}}}})
    raw.append({"tool": "setWorldRoot", "arguments": {"root_location_id": root_id, "adopt_top_level": True, "reparent_previous": True}})
    for relation in projection.get("relations", {}).values():
        if relation.get("relation") != "route":
            continue
        source = projection["entities"].get(relation.get("source_id"), {})
        target = projection["entities"].get(relation.get("target_id"), {})
        if source.get("kind") != "location" or target.get("kind") != "location":
            continue
        source_anchor, target_anchor = new_id(), new_id()
        raw.extend([
            {"tool": "upsertMapAnchor", "arguments": {"id": source_anchor, "location_id": source["id"], "name": f"{source['name']} route", "kind": "waypoint", "x": source.get("state", {}).get("x"), "y": source.get("state", {}).get("y"), "discovered": relation.get("discovered", True)}},
            {"tool": "upsertMapAnchor", "arguments": {"id": target_anchor, "location_id": target["id"], "name": f"{target['name']} route", "kind": "waypoint", "x": target.get("state", {}).get("x"), "y": target.get("state", {}).get("y"), "discovered": relation.get("discovered", True)}},
            {"tool": "upsertTravelConnection", "arguments": {"id": relation["id"], "kind": "route", "source_anchor_id": source_anchor, "target_anchor_id": target_anchor, "travel_minutes": max(0, int(relation.get("travel_minutes", 0))), "modes": relation.get("modes", ["walk"]), "bidirectional": relation.get("bidirectional", True), "enabled": not relation.get("blocked", False), "discovered": relation.get("discovered", True), "legacy_migration": True}},
        ])
    encounter_groups: dict[str, list[dict[str, Any]]] = {}
    for location in projection["entities"].values():
        state = location.get("state", {})
        if location.get("kind") == "location" and state.get("random_encounter") and state.get("parent_location_id"):
            encounter_groups.setdefault(str(state["parent_location_id"]), []).append({"location_id": location["id"], "weight": float(state.get("encounter_weight", 1))})
    raw.extend({"tool": "upsertEncounterRule", "arguments": {"location_id": parent_id, "probability": 0, "candidates": candidates, "discovered": True}} for parent_id, candidates in encounter_groups.items())
    try:
        transaction, _ = _commit_spatial_mutations(project_id, raw, "Migrated legacy location map")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return {"changed": True, "root_location_id": root_id, "transaction_id": transaction["id"]}


@app.put("/api/projects/{project_id}/spatial/anchors")
async def upsert_map_anchor(project_id: str, request: MapAnchorUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "upsertMapAnchor", request.model_dump(exclude_none=True), "Map anchor changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.put("/api/projects/{project_id}/spatial/barriers")
async def upsert_map_barrier(project_id: str, request: BarrierUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "upsertBarrier", request.model_dump(mode="json", exclude_none=True), "Map barrier changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.put("/api/projects/{project_id}/spatial/connections")
async def upsert_travel_connection(project_id: str, request: TravelConnectionUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "upsertTravelConnection", request.model_dump(mode="json", exclude_none=True), "Travel connection changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.put("/api/projects/{project_id}/spatial/encounters")
async def upsert_encounter_rule(project_id: str, request: EncounterRuleUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "upsertEncounterRule", request.model_dump(mode="json", exclude_none=True), "Encounter rule changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.patch("/api/projects/{project_id}/spatial/barriers/{barrier_id}/geometry")
async def edit_barrier_geometry(project_id: str, barrier_id: str, request: GeometryEditRequest) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "editMapGeometry", {"barrier_id": barrier_id, **request.model_dump(exclude_none=True)}, "Barrier geometry changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.put("/api/projects/{project_id}/spatial/{kind}/{object_id}/discovery")
async def set_spatial_discovery(project_id: str, kind: str, object_id: str, request: MapDiscoveryUpdate) -> dict[str, Any]:
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, "setMapDiscovery", {"kind": kind, "id": object_id, "discovered": request.discovered}, "Map discovery changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return arguments


@app.delete("/api/projects/{project_id}/spatial/{kind}/{object_id}", status_code=204)
async def remove_spatial_object(project_id: str, kind: str, object_id: str) -> None:
    try:
        transaction, _ = _commit_spatial_mutation(project_id, "removeMapObject", {"kind": kind, "id": object_id}, "Map object removed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})


@app.get("/api/projects/{project_id}/spatial/travel/preview")
async def preview_spatial_travel(project_id: str, character_id: str, location_id: str, mode: str = "walk") -> dict[str, Any]:
    require_project(project_id)
    from app.services.spatial import SpatialService, SpatialValidationError
    try:
        return SpatialService(scheduler.world.projection(project_id)).preview(character_id, location_id, mode)
    except SpatialValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/projects/{project_id}/spatial/travel/{action}")
async def perform_spatial_travel(project_id: str, action: str, request: TravelActionRequest) -> dict[str, Any]:
    tools = {"to": "travelTo", "towards": "travelTowards", "explore": "exploreFor", "resume": "resumeTravel"}
    if action not in tools:
        raise HTTPException(404, "Unknown travel action")
    try:
        transaction, arguments = _commit_spatial_mutation(project_id, tools[action], request.model_dump(exclude_none=True), f"Travel {action}")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    await events.publish("environment", {"project_id": project_id, "action": "location_changed"})
    return arguments["itinerary"]


@app.get("/api/projects/{project_id}/environment/settings")
async def get_environment_settings(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return environment.settings(project_id)


@app.put("/api/projects/{project_id}/environment/settings")
async def update_environment_settings(project_id: str, request: EnvironmentSettingsUpdate) -> dict[str, Any]:
    require_project(project_id); environment.ensure_project(project_id)
    if not db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=? AND enabled=1", (request.initial_weather_id, project_id)):
        raise HTTPException(422, "Initial weather must be enabled")
    if request.auto_generate_backgrounds and not request.background_workflow_id:
        raise HTTPException(422, "Automatic background generation requires a workflow")
    if request.background_workflow_id and not db.fetch_one("SELECT id FROM workflow_presets WHERE id=?", (request.background_workflow_id,)):
        raise HTTPException(422, "Background workflow not found")
    db.execute(
        "UPDATE project_environment_settings SET enabled=?,ai_create_locations=?,ai_propose_weather=?,auto_generate_backgrounds=?,background_workflow_id=?,initial_weather_id=?,perception_stat_key=?,revision=revision+1,updated_at=? WHERE project_id=?",
        (int(request.enabled), int(request.ai_create_locations), int(request.ai_propose_weather), int(request.auto_generate_backgrounds), request.background_workflow_id, request.initial_weather_id, request.perception_stat_key, utc_now(), project_id),
    )
    await events.publish("environment", {"project_id": project_id, "action": "settings_changed"})
    return environment.settings(project_id)


@app.post("/api/projects/{project_id}/environment/weather", status_code=201)
async def create_weather(project_id: str, request: WeatherDefinitionUpdate) -> dict[str, Any]:
    require_project(project_id); now, weather_id = utc_now(), new_id()
    try:
        db.execute("INSERT INTO weather_definitions(id,project_id,name,description,imagegen_description,tags_json,image_tags_json,enabled,visibility_multiplier,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (weather_id, project_id, request.name.strip(), request.description, request.imagegen_description, json.dumps(request.tags), json.dumps(request.image_tags), int(request.enabled), request.visibility_multiplier, now, now))
    except Exception as exc:
        raise HTTPException(409, "A weather definition with that name already exists") from exc
    await events.publish("environment", {"project_id": project_id, "action": "weather_changed"})
    return next(item for item in environment.settings(project_id)["weather"] if item["id"] == weather_id)


@app.put("/api/projects/{project_id}/environment/weather/{weather_id}")
async def update_weather(project_id: str, weather_id: str, request: WeatherDefinitionUpdate) -> dict[str, Any]:
    require_project(project_id)
    if not db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=?", (weather_id, project_id)):
        raise HTTPException(404, "Weather not found")
    settings = db.fetch_one("SELECT initial_weather_id FROM project_environment_settings WHERE project_id=?", (project_id,)) or {}
    if not request.enabled and settings.get("initial_weather_id") == weather_id:
        raise HTTPException(422, "The initial weather cannot be disabled")
    db.execute("UPDATE weather_definitions SET name=?,description=?,imagegen_description=?,tags_json=?,image_tags_json=?,enabled=?,visibility_multiplier=?,updated_at=? WHERE id=?", (request.name.strip(), request.description, request.imagegen_description, json.dumps(request.tags), json.dumps(request.image_tags), int(request.enabled), request.visibility_multiplier, utc_now(), weather_id))
    if not request.enabled:
        project = require_project(project_id)
        projection = scheduler.world.projection(project_id)
        if projection.get("current_weather_id") == weather_id:
            focus = projection.get("entities", {}).get(projection.get("focused_character_id"))
            if not focus or not focus.get("state", {}).get("player_controlled"):
                focus = next((item for item in projection.get("entities", {}).values() if item.get("kind") == "character" and item.get("state", {}).get("player_controlled")), None)
            if focus:
                mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "setSceneEnvironment", "arguments": {"focused_character_id": focus["id"], "player_action": projection.get("player_action") or "standing", "weather_id": settings["initial_weather_id"]}}], provenance="author")
                if project.get("active_node_id"):
                    scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary="Disabled active weather")
                else:
                    scheduler.world.commit_root(project_id, mutations, provenance="author", summary="Disabled active weather")
    await events.publish("environment", {"project_id": project_id, "action": "weather_changed"})
    return next(item for item in environment.settings(project_id)["weather"] if item["id"] == weather_id)


@app.delete("/api/projects/{project_id}/environment/weather/{weather_id}", status_code=204)
async def delete_weather(project_id: str, weather_id: str) -> None:
    require_project(project_id)
    settings = db.fetch_one("SELECT initial_weather_id FROM project_environment_settings WHERE project_id=?", (project_id,)) or {}
    if settings.get("initial_weather_id") == weather_id: raise HTTPException(422, "The initial weather cannot be deleted")
    db.execute("DELETE FROM weather_definitions WHERE id=? AND project_id=?", (weather_id, project_id))
    await events.publish("environment", {"project_id": project_id, "action": "weather_changed"})


@app.put("/api/projects/{project_id}/environment/weather/{weather_id}/transitions")
async def update_weather_transitions(project_id: str, weather_id: str, request: WeatherTransitionsUpdate) -> dict[str, Any]:
    require_project(project_id)
    valid = {row["id"] for row in db.fetch_all("SELECT id FROM weather_definitions WHERE project_id=?", (project_id,))}
    if weather_id not in valid or not set(request.target_weather_ids) <= valid:
        raise HTTPException(422, "Transitions must reference enabled project weather")
    with db._lock, db.connect() as connection:
        connection.execute("DELETE FROM weather_transitions WHERE project_id=? AND source_weather_id=?", (project_id, weather_id))
        connection.executemany("INSERT INTO weather_transitions(project_id,source_weather_id,target_weather_id) VALUES(?,?,?)", [(project_id, weather_id, value) for value in dict.fromkeys(request.target_weather_ids) if value != weather_id])
    await events.publish("environment", {"project_id": project_id, "action": "weather_changed"})
    return environment.settings(project_id)


@app.put("/api/projects/{project_id}/environment/time-phases")
async def update_time_phases(project_id: str, request: TimePhasesUpdate) -> dict[str, Any]:
    require_project(project_id)
    if not any(item.enabled for item in request.phases):
        raise HTTPException(422, "At least one time phase must be enabled")
    with db._lock, db.connect() as connection:
        existing = {row["id"] for row in connection.execute("SELECT id FROM time_phases WHERE project_id=?", (project_id,)).fetchall()}
        requested_ids = {item.id for item in request.phases if item.id}
        connection.execute("UPDATE time_phases SET position=position+1000 WHERE project_id=?", (project_id,))
        for position, item in enumerate(request.phases):
            phase_id = item.id or new_id()
            if phase_id in existing:
                connection.execute("UPDATE time_phases SET name=?,duration_minutes=?,description=?,imagegen_description=?,position=?,enabled=?,visibility_multiplier=? WHERE id=? AND project_id=?", (item.name.strip(), item.duration_minutes, item.description, item.imagegen_description, position, int(item.enabled), item.visibility_multiplier, phase_id, project_id))
            else:
                connection.execute("INSERT INTO time_phases(id,project_id,name,duration_minutes,description,imagegen_description,position,enabled,visibility_multiplier) VALUES(?,?,?,?,?,?,?,?,?)", (phase_id, project_id, item.name.strip(), item.duration_minutes, item.description, item.imagegen_description, position, int(item.enabled), item.visibility_multiplier))
        for removed_id in existing - requested_ids:
            connection.execute("DELETE FROM time_phases WHERE id=? AND project_id=?", (removed_id, project_id))
        connection.execute("UPDATE project_environment_settings SET revision=revision+1,updated_at=? WHERE project_id=?", (utc_now(), project_id))
    await events.publish("environment", {"project_id": project_id, "action": "time_changed"})
    return environment.settings(project_id)


@app.post("/api/projects/{project_id}/environment/time-phases", status_code=201)
async def create_time_phase(project_id: str, request: TimePhaseItem) -> dict[str, Any]:
    require_project(project_id); phase_id = new_id()
    position = int((db.fetch_one("SELECT COALESCE(MAX(position),-1)+1 position FROM time_phases WHERE project_id=?", (project_id,)) or {"position": 0})["position"])
    db.execute("INSERT INTO time_phases(id,project_id,name,duration_minutes,description,imagegen_description,position,enabled,visibility_multiplier) VALUES(?,?,?,?,?,?,?,?,?)", (phase_id, project_id, request.name.strip(), request.duration_minutes, request.description, request.imagegen_description, position, int(request.enabled), request.visibility_multiplier))
    await events.publish("environment", {"project_id": project_id, "action": "time_changed"})
    return next(item for item in environment.settings(project_id)["time_phases"] if item["id"] == phase_id)


@app.put("/api/projects/{project_id}/environment/time-phases/{phase_id}")
async def update_time_phase(project_id: str, phase_id: str, request: TimePhaseItem) -> dict[str, Any]:
    require_project(project_id)
    if not db.fetch_one("SELECT id FROM time_phases WHERE id=? AND project_id=?", (phase_id, project_id)): raise HTTPException(404, "Time phase not found")
    if not request.enabled and (db.fetch_one("SELECT COUNT(*) n FROM time_phases WHERE project_id=? AND enabled=1 AND id<>?", (project_id, phase_id)) or {"n": 0})["n"] == 0: raise HTTPException(422, "At least one time phase must be enabled")
    db.execute("UPDATE time_phases SET name=?,duration_minutes=?,description=?,imagegen_description=?,enabled=?,visibility_multiplier=? WHERE id=? AND project_id=?", (request.name.strip(), request.duration_minutes, request.description, request.imagegen_description, int(request.enabled), request.visibility_multiplier, phase_id, project_id))
    await events.publish("environment", {"project_id": project_id, "action": "time_changed"})
    return next(item for item in environment.settings(project_id)["time_phases"] if item["id"] == phase_id)


@app.delete("/api/projects/{project_id}/environment/time-phases/{phase_id}", status_code=204)
async def delete_time_phase(project_id: str, phase_id: str) -> None:
    require_project(project_id)
    if (db.fetch_one("SELECT COUNT(*) n FROM time_phases WHERE project_id=?", (project_id,)) or {"n": 0})["n"] <= 1: raise HTTPException(422, "At least one time phase must remain")
    db.execute("DELETE FROM time_phases WHERE id=? AND project_id=?", (phase_id, project_id))
    await events.publish("environment", {"project_id": project_id, "action": "time_changed"})


@app.put("/api/projects/{project_id}/environment/time-phase-order")
async def reorder_time_phases(project_id: str, request: TimePhaseOrderUpdate) -> dict[str, Any]:
    require_project(project_id)
    existing = {row["id"] for row in db.fetch_all("SELECT id FROM time_phases WHERE project_id=?", (project_id,))}
    if len(request.phase_ids) != len(set(request.phase_ids)) or set(request.phase_ids) != existing: raise HTTPException(422, "Order must contain every time phase exactly once")
    with db._lock, db.connect() as connection:
        connection.execute("UPDATE time_phases SET position=position+1000 WHERE project_id=?", (project_id,))
        for position, phase_id in enumerate(request.phase_ids): connection.execute("UPDATE time_phases SET position=? WHERE id=?", (position, phase_id))
    await events.publish("environment", {"project_id": project_id, "action": "time_changed"})
    return environment.settings(project_id)


def _location_state(request: EnvironmentLocationUpdate) -> dict[str, Any]:
    return {
        "parent_location_id": request.parent_location_id, "exposure": request.exposure,
        "description": request.description, "imagegen_description": request.imagegen_description,
        "image_tags": request.image_tags, "enabled": request.enabled,
        "random_encounter": request.random_encounter, "discovered": request.discovered,
        "hidden": request.hidden,
        "x": request.x, "y": request.y,
        "topology": request.topology, "occupancy": request.occupancy,
        "boundary_access": request.boundary_access, "spatial_kind": request.spatial_kind,
        "minutes_per_unit": request.minutes_per_unit,
        "base_visibility_units": request.base_visibility_units,
        "encounter_rate": request.encounter_rate,
        "footprint": request.footprint, "local_bounds": request.local_bounds,
    }


@app.post("/api/projects/{project_id}/environment/locations", status_code=201)
async def create_environment_location(project_id: str, request: EnvironmentLocationUpdate) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "createEntity", "arguments": {"kind": "location", "name": request.name, "aliases": [], "tags": request.tags, "state": _location_state(request)}}], provenance="author")
        if project.get("active_node_id"):
            transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary=f"Created {request.name}")
        else:
            transaction = scheduler.world.commit_root(project_id, mutations, provenance="author", summary=f"Created {request.name}")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    await events.publish("environment", {"project_id": project_id, "action": "location_changed"})
    return scheduler.world.entity_card(project_id, mutations[0].arguments["entity_id"])


@app.put("/api/projects/{project_id}/environment/locations/{location_id}")
async def update_environment_location(project_id: str, location_id: str, request: EnvironmentLocationUpdate) -> dict[str, Any]:
    project = require_project(project_id)
    current = scheduler.world.projection(project_id).get("entities", {}).get(location_id)
    if not current or current.get("kind") != "location": raise HTTPException(404, "Location not found")
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "updateEntity", "arguments": {"entity_id": location_id, "name": request.name, "tags": request.tags, "patch": _location_state(request)}}], provenance="author")
        if project.get("active_node_id"):
            transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary=f"Updated {request.name}")
        else:
            transaction = scheduler.world.commit_root(project_id, mutations, provenance="author", summary=f"Updated {request.name}")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    await events.publish("environment", {"project_id": project_id, "action": "location_changed"})
    return scheduler.world.entity_card(project_id, location_id)


@app.put("/api/projects/{project_id}/environment/scene")
async def set_scene_environment(project_id: str, request: SceneEnvironmentUpdate) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "setSceneEnvironment", "arguments": request.model_dump(exclude_none=True)}], provenance="author")
        if project.get("active_node_id"):
            scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary="Environment changed")
        else:
            scheduler.world.commit_root(project_id, mutations, provenance="author", summary="Environment changed")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("environment", {"project_id": project_id, "action": "scene_changed"})
    return environment.scene(project_id, scheduler.world.projection(project_id))


@app.get("/api/projects/{project_id}/environment/locations/{location_id}/backgrounds")
async def list_location_backgrounds(project_id: str, location_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    return db.fetch_all("SELECT b.*,m.status,m.file_path,m.prompt,m.negative_prompt FROM location_backgrounds b JOIN entity_media_assets m ON m.id=b.media_asset_id WHERE b.project_id=? AND b.location_id=? ORDER BY b.position,b.created_at", (project_id, location_id))


@app.post("/api/projects/{project_id}/environment/locations/{location_id}/backgrounds", status_code=201)
async def create_location_background(project_id: str, location_id: str, request: LocationBackgroundCreate) -> dict[str, Any]:
    require_project(project_id); entity = db.fetch_one("SELECT id FROM world_entities WHERE id=? AND project_id=? AND kind='location'", (location_id, project_id))
    if not entity: raise HTTPException(404, "Location not found")
    if request.weather_id and not db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=?", (request.weather_id, project_id)): raise HTTPException(422, "Weather condition not found")
    if request.time_phase_id and not db.fetch_one("SELECT id FROM time_phases WHERE id=? AND project_id=?", (request.time_phase_id, project_id)): raise HTTPException(422, "Time condition not found")
    now, asset_id, background_id = utc_now(), new_id(), new_id()
    db.execute("INSERT INTO entity_media_assets(id,project_id,entity_id,kind,source,status,prompt,negative_prompt,featured,created_at,updated_at) VALUES(?,?,?,'location','suggested','suggested',?,?,0,?,?)", (asset_id, project_id, location_id, request.prompt, request.negative_prompt, now, now))
    db.execute("INSERT INTO location_backgrounds(id,project_id,location_id,media_asset_id,weather_id,time_phase_id,position,created_at) VALUES(?,?,?,?,?,?,0,?)", (background_id, project_id, location_id, asset_id, request.weather_id, request.time_phase_id, now))
    return {"id": background_id, "media_asset_id": asset_id, "status": "suggested", **request.model_dump()}


@app.get("/api/projects/{project_id}/environment/ambient")
async def list_ambient(project_id: str) -> dict[str, Any]:
    require_project(project_id); environment.index_sounds(project_id)
    variants = db.fetch_all("SELECT * FROM ambient_variants WHERE project_id=? ORDER BY source_path,label", (project_id,))
    for item in variants:
        item["tags"] = json.loads(item.pop("tags_json")); item["enabled"] = bool(item["enabled"]); item["available"] = bool(item["available"])
        item["url"] = "/sounds/" + item["source_path"]
    return {"variants": variants, "assignments": db.fetch_all("SELECT * FROM ambient_assignments WHERE project_id=? ORDER BY owner_type,owner_id", (project_id,))}


@app.get("/api/projects/{project_id}/noises")
async def list_noises(project_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    return sound.list_noises(project_id, refresh=True)


@app.put("/api/projects/{project_id}/noises/{noise_id}")
async def update_noise(
    project_id: str,
    noise_id: str,
    request: NoiseVariantUpdate,
) -> dict[str, Any]:
    require_project(project_id)
    if not data.sound.noise_variant(project_id, noise_id):
        raise HTTPException(404, "Noise not found")
    data.sound.update_noise_variant(
        project_id,
        noise_id,
        label=request.label,
        playback_rate=request.playback_rate,
        default_gain=request.default_gain,
        tags=request.tags,
        enabled=request.enabled,
    )
    return next(
        item
        for item in sound.list_noises(project_id)
        if item["id"] == noise_id
    )


@app.post("/api/projects/{project_id}/noises/{noise_id}/play")
async def play_noise(project_id: str, noise_id: str) -> dict[str, Any]:
    require_project(project_id)
    payload = await sound.play_noise(
        project_id,
        noise_id,
        source="manual",
    )
    if not payload:
        raise HTTPException(422, "Noise is disabled or unavailable")
    return payload


@app.post("/api/projects/{project_id}/environment/ambient/variants", status_code=201)
async def create_ambient_variant(project_id: str, request: AmbientVariantCreate) -> dict[str, Any]:
    require_project(project_id)
    base = db.fetch_one("SELECT source_path,available FROM ambient_variants WHERE project_id=? AND source_path=? LIMIT 1", (project_id, request.source_path))
    if not base:
        raise HTTPException(422, "Sound source is not in public/sounds")
    variant_id, now = new_id(), utc_now()
    db.execute("INSERT INTO ambient_variants(id,project_id,source_path,label,playback_rate,default_gain,tags_json,enabled,available,derived,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?)", (variant_id, project_id, request.source_path, request.label, request.playback_rate, request.default_gain, json.dumps(request.tags), int(request.enabled), base["available"], now, now))
    return {"id": variant_id}


@app.put("/api/projects/{project_id}/environment/ambient/variants/{variant_id}")
async def update_ambient_variant(project_id: str, variant_id: str, request: AmbientVariantCreate) -> dict[str, Any]:
    require_project(project_id)
    db.execute("UPDATE ambient_variants SET label=?,playback_rate=?,default_gain=?,tags_json=?,enabled=?,updated_at=? WHERE id=? AND project_id=?", (request.label, request.playback_rate, request.default_gain, json.dumps(request.tags), int(request.enabled), utc_now(), variant_id, project_id))
    await events.publish("environment", {"project_id": project_id, "action": "ambient_changed"})
    return {"id": variant_id}


@app.post("/api/projects/{project_id}/environment/ambient/assignments", status_code=201)
async def create_ambient_assignment(project_id: str, request: AmbientAssignmentCreate) -> dict[str, Any]:
    require_project(project_id)
    if not db.fetch_one("SELECT id FROM ambient_variants WHERE id=? AND project_id=?", (request.variant_id, project_id)):
        raise HTTPException(422, "Ambient variant not found")
    assignment_id = new_id()
    db.execute("INSERT INTO ambient_assignments(id,project_id,owner_type,owner_id,selector_type,selector_value,weather_id,time_phase_id,variant_id) VALUES(?,?,?,?,?,?,?,?,?)", (assignment_id, project_id, request.owner_type, request.owner_id, request.selector_type, request.selector_value, request.weather_id, request.time_phase_id, request.variant_id))
    await events.publish("environment", {"project_id": project_id, "action": "ambient_changed"})
    return {"id": assignment_id}


@app.delete("/api/projects/{project_id}/environment/ambient/assignments/{assignment_id}", status_code=204)
async def delete_ambient_assignment(project_id: str, assignment_id: str) -> None:
    require_project(project_id); db.execute("DELETE FROM ambient_assignments WHERE id=? AND project_id=?", (assignment_id, project_id))
    await events.publish("environment", {"project_id": project_id, "action": "ambient_changed"})


@app.put("/api/projects/{project_id}/environment/ambient/assignments/{owner_type}/{owner_id}")
async def replace_ambient_assignments(project_id: str, owner_type: str, owner_id: str, request: AmbientSoundSetsUpdate) -> list[dict[str, Any]]:
    require_project(project_id)
    try:
        result = environment.replace_ambient_sets(project_id, owner_type, owner_id, [item.model_dump() for item in request.sets])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("environment", {"project_id": project_id, "action": "ambient_changed"})
    return result


@app.get("/api/projects/{project_id}/environment/weather-proposals")
async def list_weather_proposals(project_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    rows = db.fetch_all("SELECT * FROM weather_proposals WHERE project_id=? ORDER BY created_at DESC", (project_id,))
    for row in rows:
        for key in ("tags_json", "image_tags_json", "transitions_json"): row[key.removesuffix("_json")] = json.loads(row.pop(key))
    return rows


@app.put("/api/projects/{project_id}/environment/weather-proposals/{proposal_id}")
async def decide_weather_proposal(project_id: str, proposal_id: str, request: WeatherProposalDecision) -> dict[str, Any]:
    require_project(project_id); proposal = db.fetch_one("SELECT * FROM weather_proposals WHERE id=? AND project_id=? AND status='pending'", (proposal_id, project_id))
    if not proposal: raise HTTPException(404, "Pending weather proposal not found")
    if request.action == "approve":
        now, weather_id = utc_now(), new_id()
        db.execute("INSERT INTO weather_definitions(id,project_id,name,description,tags_json,image_tags_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,1,?,?)", (weather_id, project_id, proposal["name"], proposal["description"], proposal["tags_json"], proposal["image_tags_json"], now, now))
        valid = {row["id"] for row in db.fetch_all("SELECT id FROM weather_definitions WHERE project_id=? AND enabled=1", (project_id,))}
        for source_id in json.loads(proposal["transitions_json"]):
            if source_id in valid and source_id != weather_id:
                db.execute("INSERT OR IGNORE INTO weather_transitions(project_id,source_weather_id,target_weather_id) VALUES(?,?,?)", (project_id, source_id, weather_id))
    db.execute("UPDATE weather_proposals SET status=?,updated_at=? WHERE id=?", ("approved" if request.action == "approve" else "rejected", utc_now(), proposal_id))
    await events.publish("environment", {"project_id": project_id, "action": "weather_proposal_decided"})
    return {"status": "approved" if request.action == "approve" else "rejected"}


@app.get("/api/projects/{project_id}/entities")
async def search_world_entities(
    project_id: str, query: str = "", kind: str | None = None, head_node_id: str | None = None,
    pov_character_id: str | None = None, narration_mode: str = "third_omniscient",
) -> list[dict[str, Any]]:
    require_project(project_id)
    return scheduler.world.search(
        project_id, query, head_node_id=head_node_id, pov_character_id=pov_character_id,
        narration_mode=narration_mode, kinds=[kind] if kind else None, limit=50,
    )


@app.post("/api/projects/{project_id}/entities", status_code=201)
async def create_world_entity(project_id: str, request: WorldEntityCreate) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(
            project_id, project.get("active_node_id"), [{"tool": "createEntity", "arguments": request.model_dump()}],
            provenance="author",
        )
        if project.get("active_node_id"):
            transaction = scheduler.world.commit_to_existing_node(
                project_id, project["active_node_id"], mutations, provenance="author", summary=f"Created {request.name}"
            )
        else:
            transaction = scheduler.world.commit_root(project_id, mutations, provenance="author", summary=f"Created {request.name}")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    entity_id = mutations[0].arguments["entity_id"]
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return scheduler.world.entity_card(project_id, entity_id)


@app.post("/api/projects/{project_id}/world/clone", status_code=201)
async def clone_world_subgraph(project_id: str, request: WorldCloneRequest) -> dict[str, Any]:
    require_project(project_id)
    require_project(request.source_project_id)
    try:
        result = world_clone.clone(project_id, **request.model_dump())
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": result["transaction_id"]})
    return result


@app.patch("/api/projects/{project_id}/entities/{entity_id}")
async def update_world_entity(project_id: str, entity_id: str, request: WorldEntityUpdate) -> dict[str, Any]:
    project = require_project(project_id)
    bullet_fields = {"bullethell_default_mode_id", "bullethell_forced_mode_id", "bullethell_skill_ids"}
    if bullet_fields & set(request.patch):
        current = scheduler.world.projection(project_id).get("entities", {}).get(entity_id)
        if not current or current.get("kind") != "character":
            raise HTTPException(422, "Bullet-hell assignments are only valid for characters")
        settings = scheduler.minigames.bullethell.project_settings(project_id)
        for field in ("bullethell_default_mode_id", "bullethell_forced_mode_id"):
            selected_mode = request.patch.get(field)
            if selected_mode is not None and selected_mode not in settings["allowed_mode_ids"]:
                raise HTTPException(422, f"{field} must reference a mode enabled for this project")
        assigned_skills = request.patch.get("bullethell_skill_ids", [])
        if not isinstance(assigned_skills, list) or not set(assigned_skills) <= set(settings["allowed_skill_ids"]):
            raise HTTPException(422, "bullethell_skill_ids must reference skills enabled for this project")
    arguments = {"entity_id": entity_id, "patch": request.patch}
    if request.name is not None:
        arguments["name"] = request.name.strip()
    if request.aliases is not None:
        arguments["aliases"] = request.aliases
    if request.tags is not None:
        arguments["tags"] = request.tags
    try:
        mutations = scheduler.world.normalize_mutations(
            project_id, project.get("active_node_id"), [{"tool": "updateEntity", "arguments": arguments}], provenance="author"
        )
        if project.get("active_node_id"):
            transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author")
        else:
            transaction = scheduler.world.commit_root(project_id, mutations, provenance="author", summary="Entity updated")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return scheduler.world.entity_card(project_id, entity_id)


@app.post("/api/projects/{project_id}/entities/{entity_id}/archive")
async def archive_world_entity(project_id: str, entity_id: str) -> dict[str, Any]:
    require_idle_project(project_id)
    return await update_world_entity(project_id, entity_id, WorldEntityUpdate(patch={"archived": True}))


@app.post("/api/projects/{project_id}/entities/{entity_id}/restore")
async def restore_world_entity(project_id: str, entity_id: str) -> dict[str, Any]:
    return await update_world_entity(project_id, entity_id, WorldEntityUpdate(patch={"archived": False}))


@app.get("/api/projects/{project_id}/entities/{entity_id}/delete-impact")
async def entity_delete_impact(project_id: str, entity_id: str) -> dict[str, Any]:
    require_project(project_id)
    entity = db.fetch_one("SELECT * FROM world_entities WHERE id = ? AND project_id = ?", (entity_id, project_id))
    if not entity:
        raise HTTPException(404, "World entity not found")
    like = f"%{entity_id}%"
    transactions = db.fetch_all(
        "SELECT DISTINCT t.id FROM world_transactions t JOIN world_events e ON e.transaction_id=t.id WHERE t.project_id=? AND (e.entity_id=? OR e.payload_json LIKE ?)",
        (project_id, entity_id, like),
    )
    counts = {
        "transactions": len(transactions),
        "lore_versions": (db.fetch_one("SELECT COUNT(*) n FROM lore_card_versions WHERE entity_id=?", (entity_id,)) or {"n": 0})["n"],
        "appearances": (db.fetch_one("SELECT COUNT(*) n FROM scene_appearances WHERE entity_id=?", (entity_id,)) or {"n": 0})["n"],
        "media": (db.fetch_one("SELECT COUNT(*) n FROM entity_media_assets WHERE entity_id=?", (entity_id,)) or {"n": 0})["n"],
        "outfits": (db.fetch_one("SELECT COUNT(*) n FROM entity_outfits WHERE entity_id=?", (entity_id,)) or {"n": 0})["n"],
    }
    return {"entity_id": entity_id, "name": entity["canonical_name"], "counts": counts, "confirmation": entity["canonical_name"]}


@app.delete("/api/projects/{project_id}/entities/{entity_id}")
async def hard_delete_world_entity(project_id: str, entity_id: str, request: HardDeleteConfirm) -> dict[str, Any]:
    impact = await entity_delete_impact(project_id, entity_id)
    require_idle_project(project_id)
    if request.confirmation != impact["confirmation"]:
        raise HTTPException(422, f"Type {impact['confirmation']} to confirm permanent deletion")
    assets = db.fetch_all("SELECT file_path FROM entity_media_assets WHERE entity_id=? AND file_path IS NOT NULL", (entity_id,))
    like = f"%{entity_id}%"
    transactions = db.fetch_all(
        "SELECT DISTINCT t.id FROM world_transactions t JOIN world_events e ON e.transaction_id=t.id WHERE t.project_id=? AND (e.entity_id=? OR e.payload_json LIKE ?)",
        (project_id, entity_id, like),
    )
    for tx in transactions:
        db.execute("DELETE FROM world_transactions WHERE id=?", (tx["id"],))
    db.execute("DELETE FROM lore_card_search WHERE entity_id=?", (entity_id,))
    db.execute("DELETE FROM world_entities WHERE id=? AND project_id=?", (entity_id, project_id))
    lifecycle.release_paths([asset["file_path"] for asset in assets])
    db.execute("DELETE FROM world_projection_cache WHERE project_id=?", (project_id,))
    await events.publish("memory_changed", {"project_id": project_id, "entity_id": entity_id, "hard_deleted": True})
    return impact


@app.post("/api/projects/{project_id}/mutations", status_code=201)
async def apply_world_mutations(project_id: str, request: WorldMutationBatch) -> dict[str, Any]:
    project = require_project(project_id)
    head = project.get("active_node_id")
    try:
        mutations = scheduler.world.normalize_mutations(
            project_id, head, request.mutations, provenance="author"
        )
        transaction = (
            scheduler.world.commit_to_existing_node(
                project_id, head, mutations, provenance="author", summary=request.summary
            )
            if head else scheduler.world.commit_root(
                project_id, mutations, provenance="author", summary=request.summary
            )
        )
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return {"transaction": transaction, "projection": scheduler.world.projection(project_id, head, use_cache=False)}


@app.delete("/api/projects/{project_id}/relationships/{relationship_id}")
async def remove_relationship(project_id: str, relationship_id: str) -> dict[str, Any]:
    return await apply_world_mutations(
        project_id,
        WorldMutationBatch(mutations=[{"tool": "removeRelationship", "arguments": {"relationship_id": relationship_id}}], summary="Relationship removed"),
    )


@app.get("/api/projects/{project_id}/entities/{entity_id}/history")
async def entity_history(project_id: str, entity_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    rows = db.fetch_all(
        "SELECT e.*, t.story_node_id, t.provenance, t.summary, t.display_time, t.branch_sequence "
        "FROM world_events e JOIN world_transactions t ON t.id = e.transaction_id "
        "WHERE t.project_id = ? AND e.entity_id = ? ORDER BY e.created_at", (project_id, entity_id),
    )
    for row in rows:
        row["payload"] = json.loads(row.pop("payload_json"))
    return rows


@app.patch("/api/projects/{project_id}/characters/{entity_id}/npc")
async def update_npc_settings(project_id: str, entity_id: str, request: NpcSettingsUpdate) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutation = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "updateEntity", "arguments": {"entity_id": entity_id, "patch": request.model_dump()}}], provenance="author")
        if scheduler.world.projection(project_id)["entities"].get(entity_id, {}).get("state", {}).get("player_controlled") and request.autonomy_enabled:
            raise WorldValidationError("Player-controlled characters cannot enable NPC autonomy")
        transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutation, provenance="author", summary="NPC autonomy updated") if project.get("active_node_id") else scheduler.world.commit_root(project_id, mutation, provenance="author", summary="NPC autonomy updated")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return scheduler.world.entity_card(project_id, entity_id)


@app.get("/api/entities/{entity_id}/outfits")
async def list_outfits(entity_id: str) -> list[dict[str, Any]]:
    rows = db.fetch_all(
        "SELECT * FROM entity_outfits WHERE entity_id = ? ORDER BY name",
        (entity_id,),
    )
    return [
        outfit_from_record(row).model_dump(mode="json")
        for row in rows
    ]


@app.post("/api/entities/{entity_id}/outfits", status_code=201)
async def create_outfit(entity_id: str, request: OutfitCreate) -> dict[str, Any]:
    entity = db.fetch_one(
        "SELECT * FROM world_entities WHERE id = ? AND kind = 'character'",
        (entity_id,),
    )
    if not entity:
        raise HTTPException(404, "Character not found")
    outfit_id, now = new_id(), utc_now()
    try:
        db.execute(
            "INSERT INTO entity_outfits("
            "id,entity_id,name,description,imagegen_description,equipment_json,"
            "created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                outfit_id,
                entity_id,
                request.name.strip(),
                request.description,
                request.imagegen_description,
                json.dumps(request.equipment),
                now,
                now,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            409,
            "An outfit with that name already exists",
        ) from exc
    row = db.fetch_one(
        "SELECT * FROM entity_outfits WHERE id=?",
        (outfit_id,),
    ) or {}
    return outfit_from_record(row).model_dump(mode="json")


@app.put("/api/outfits/{outfit_id}")
async def update_outfit(outfit_id: str, request: OutfitCreate) -> dict[str, Any]:
    if not db.fetch_one(
        "SELECT id FROM entity_outfits WHERE id = ?",
        (outfit_id,),
    ):
        raise HTTPException(404, "Outfit not found")
    try:
        db.execute(
            "UPDATE entity_outfits SET name=?,description=?,"
            "imagegen_description=?,equipment_json=?,updated_at=? WHERE id=?",
            (
                request.name.strip(),
                request.description,
                request.imagegen_description,
                json.dumps(request.equipment),
                utc_now(),
                outfit_id,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            409,
            "An outfit with that name already exists",
        ) from exc
    row = db.fetch_one(
        "SELECT * FROM entity_outfits WHERE id=?",
        (outfit_id,),
    ) or {}
    return outfit_from_record(row).model_dump(mode="json")


@app.delete("/api/outfits/{outfit_id}", status_code=204)
async def delete_outfit(outfit_id: str) -> None:
    owner = db.fetch_one("SELECT o.id,e.project_id FROM entity_outfits o JOIN world_entities e ON e.id=o.entity_id WHERE o.id=?", (outfit_id,))
    if not owner:
        raise HTTPException(404, "Outfit not found")
    require_idle_project(owner["project_id"])
    referenced = db.fetch_one("SELECT 1 FROM scene_appearances WHERE outfit_id = ? UNION SELECT 1 FROM entity_media_assets WHERE outfit_id = ? UNION SELECT 1 FROM world_events WHERE json_extract(payload_json, '$.patch.active_outfit_id') = ? LIMIT 1", (outfit_id, outfit_id, outfit_id))
    if referenced:
        raise HTTPException(409, "Outfit is part of story or media history and cannot be deleted")
    db.execute("DELETE FROM entity_outfits WHERE id = ?", (outfit_id,))


@app.get("/api/outfits/{outfit_id}/delete-impact")
async def outfit_delete_impact(outfit_id: str) -> dict[str, Any]:
    outfit = db.fetch_one("SELECT * FROM entity_outfits WHERE id=?", (outfit_id,))
    if not outfit:
        raise HTTPException(404, "Outfit not found")
    return {"outfit_id": outfit_id, "name": outfit["name"], "confirmation": outfit["name"], "counts": {
        "appearances": int((db.fetch_one("SELECT COUNT(*) n FROM scene_appearances WHERE outfit_id=?", (outfit_id,)) or {"n": 0})["n"]),
        "media": int((db.fetch_one("SELECT COUNT(*) n FROM entity_media_assets WHERE outfit_id=?", (outfit_id,)) or {"n": 0})["n"]),
        "event_references": int((db.fetch_one("SELECT COUNT(*) n FROM world_events WHERE payload_json LIKE ?", (f"%{outfit_id}%",)) or {"n": 0})["n"]),
    }}


@app.delete("/api/outfits/{outfit_id}/purge")
async def purge_outfit(outfit_id: str, request: HardDeleteConfirm) -> dict[str, Any]:
    impact = await outfit_delete_impact(outfit_id)
    owner = db.fetch_one("SELECT e.project_id FROM entity_outfits o JOIN world_entities e ON e.id=o.entity_id WHERE o.id=?", (outfit_id,))
    require_idle_project(owner["project_id"])
    if request.confirmation != impact["confirmation"]:
        raise HTTPException(422, f"Type {impact['confirmation']} to confirm")
    paths = [row["file_path"] for row in db.fetch_all("SELECT file_path FROM entity_media_assets WHERE outfit_id=? AND file_path IS NOT NULL", (outfit_id,))]
    db.execute("DELETE FROM entity_outfits WHERE id=?", (outfit_id,))
    lifecycle.release_paths(paths)
    return impact


@app.post("/api/outfits/{outfit_id}/activate")
async def activate_outfit(outfit_id: str) -> dict[str, Any]:
    outfit = db.fetch_one("SELECT o.*, e.project_id FROM entity_outfits o JOIN world_entities e ON e.id = o.entity_id WHERE o.id = ?", (outfit_id,))
    if not outfit: raise HTTPException(404, "Outfit not found")
    project = require_project(outfit["project_id"])
    mutation = scheduler.world.normalize_mutations(outfit["project_id"], project.get("active_node_id"), [{"tool": "updateEntity", "arguments": {"entity_id": outfit["entity_id"], "patch": {"active_outfit_id": outfit_id, "equipment": json.loads(outfit["equipment_json"])}}}], provenance="author")
    transaction = scheduler.world.commit_to_existing_node(outfit["project_id"], project["active_node_id"], mutation, provenance="author", summary=f"Changed outfit to {outfit['name']}") if project.get("active_node_id") else scheduler.world.commit_root(outfit["project_id"], mutation, provenance="author", summary=f"Changed outfit to {outfit['name']}")
    await events.publish("memory_changed", {"project_id": outfit["project_id"], "transaction_id": transaction["id"]})
    return scheduler.world.entity_card(outfit["project_id"], outfit["entity_id"])


@app.get("/api/entities/{entity_id}/media")
async def list_entity_media(entity_id: str) -> list[dict[str, Any]]:
    return db.fetch_all("SELECT * FROM entity_media_assets WHERE entity_id = ? ORDER BY created_at", (entity_id,))


@app.post("/api/entities/{entity_id}/media", status_code=201)
async def create_entity_media(entity_id: str, request: EntityMediaCreate) -> dict[str, Any]:
    entity = db.fetch_one(
        "SELECT * FROM world_entities WHERE id=? AND kind='character'",
        (entity_id,),
    )
    if not entity:
        raise HTTPException(404, "Character not found")
    if request.outfit_id and not db.fetch_one(
        "SELECT id FROM entity_outfits WHERE id=? AND entity_id=?",
        (request.outfit_id, entity_id),
    ):
        raise HTTPException(422, "Outfit does not belong to this character")

    existing = db.fetch_one(
        "SELECT * FROM entity_media_assets "
        "WHERE entity_id=? AND kind=? "
        "AND COALESCE(outfit_id,'')=COALESCE(?, '') AND featured=1",
        (entity_id, request.kind, request.outfit_id),
    )
    now = utc_now()
    if existing:
        db.execute(
            "UPDATE entity_media_assets SET source='generated',prompt=?,"
            "negative_prompt=?,updated_at=? WHERE id=?",
            (request.prompt, request.negative_prompt, now, existing["id"]),
        )
        return db.fetch_one(
            "SELECT * FROM entity_media_assets WHERE id=?",
            (existing["id"],),
        ) or {}

    asset_id = new_id()
    db.execute(
        "INSERT INTO entity_media_assets("
        "id,project_id,entity_id,outfit_id,kind,source,status,prompt,"
        "negative_prompt,featured,created_at,updated_at"
        ") VALUES(?,?,?,?,?,'generated','draft',?,?,1,?,?)",
        (
            asset_id,
            entity["project_id"],
            entity_id,
            request.outfit_id,
            request.kind,
            request.prompt,
            request.negative_prompt,
            now,
            now,
        ),
    )
    return db.fetch_one(
        "SELECT * FROM entity_media_assets WHERE id=?",
        (asset_id,),
    ) or {}


@app.patch("/api/media-assets/{asset_id}")
async def update_media_asset(asset_id: str, request: MediaAssetUpdate) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM entity_media_assets WHERE id = ?", (asset_id,)): raise HTTPException(404, "Media asset not found")
    db.execute("UPDATE entity_media_assets SET prompt = ?, negative_prompt = ?, updated_at = ? WHERE id = ?", (request.prompt, request.negative_prompt, utc_now(), asset_id))
    return db.fetch_one("SELECT * FROM entity_media_assets WHERE id = ?", (asset_id,)) or {}


@app.delete("/api/media-assets/{asset_id}", status_code=204)
async def delete_media_asset(asset_id: str) -> None:
    asset = db.fetch_one("SELECT * FROM entity_media_assets WHERE id = ?", (asset_id,))
    if not asset: raise HTTPException(404, "Media asset not found")
    require_idle_project(asset["project_id"])
    db.execute("DELETE FROM entity_media_assets WHERE id = ?", (asset_id,))
    lifecycle.release_paths([asset.get("file_path")])


@app.post("/api/entities/{entity_id}/media/upload", status_code=201)
async def upload_entity_media(entity_id: str, kind: str, outfit_id: str | None = None, weather_id: str | None = None, time_phase_id: str | None = None, file: UploadFile = File(...)) -> dict[str, Any]:
    entity = db.fetch_one("SELECT * FROM world_entities WHERE id = ?", (entity_id,))
    if not entity: raise HTTPException(404, "Entity not found")
    if kind not in ({"location"} if entity["kind"] == "location" else {"portrait", "full_body"}): raise HTTPException(422, "Media kind does not match entity kind")
    if outfit_id and not db.fetch_one("SELECT id FROM entity_outfits WHERE id = ? AND entity_id = ?", (outfit_id, entity_id)): raise HTTPException(422, "Outfit does not belong to this character")
    data = await file.read()
    try: mime, suffix, _, _ = validate_image(data)
    except MediaValidationError as exc: raise HTTPException(422, str(exc)) from exc
    if (weather_id or time_phase_id) and kind != "location": raise HTTPException(422, "Conditions are only valid for location backgrounds")
    if weather_id and not db.fetch_one("SELECT id FROM weather_definitions WHERE id=? AND project_id=?", (weather_id, entity["project_id"])): raise HTTPException(422, "Weather condition not found")
    if time_phase_id and not db.fetch_one("SELECT id FROM time_phases WHERE id=? AND project_id=?", (time_phase_id, entity["project_id"])): raise HTTPException(422, "Time condition not found")
    asset = None if weather_id or time_phase_id else db.fetch_one("SELECT * FROM entity_media_assets WHERE entity_id = ? AND kind = ? AND COALESCE(outfit_id, '') = COALESCE(?, '') AND featured = 1", (entity_id, kind, outfit_id))
    asset_id, now = (asset or {}).get("id", new_id()), utc_now()
    path = store_media(db.data_dir, f"images/entities/{entity['project_id']}", asset_id, suffix, data)
    if asset:
        db.execute("UPDATE entity_media_assets SET source = 'upload', status = 'generated', file_path = ?, mime_type = ?, original_name = ?, updated_at = ? WHERE id = ?", (path, mime, file.filename, now, asset_id))
        if asset.get("file_path") and asset["file_path"] != path:
            previous = (db.data_dir / asset["file_path"]).resolve()
            if db.images_dir.resolve() in previous.parents and previous.is_file(): previous.unlink()
    else:
        db.execute("INSERT INTO entity_media_assets(id, project_id, entity_id, outfit_id, kind, source, status, file_path, mime_type, original_name, featured,created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'upload', 'generated', ?, ?, ?, ?, ?, ?)", (asset_id, entity["project_id"], entity_id, outfit_id, kind, path, mime, file.filename, 0 if weather_id or time_phase_id else 1, now, now))
    if kind == "location":
        db.execute(
            "INSERT OR IGNORE INTO location_backgrounds(id,project_id,location_id,media_asset_id,position,created_at) VALUES(?,?,?,?,0,?)",
            (new_id(), entity["project_id"], entity_id, asset_id, now),
        )
        if weather_id or time_phase_id:
            db.execute("UPDATE location_backgrounds SET weather_id=?,time_phase_id=? WHERE media_asset_id=?", (weather_id, time_phase_id, asset_id))
    await events.publish("media", {"asset_id": asset_id, "entity_id": entity_id, "status": "generated"})
    if kind == "location": await events.publish("environment", {"project_id": entity["project_id"], "action": "background_ready"})
    return db.fetch_one("SELECT * FROM entity_media_assets WHERE id = ?", (asset_id,)) or {}


@app.post("/api/media-assets/{asset_id}/generate", status_code=202)
async def generate_entity_media(asset_id: str, request: ImageGenerateRequest) -> dict[str, Any]:
    asset = db.fetch_one("SELECT * FROM entity_media_assets WHERE id = ?", (asset_id,))
    if not asset: raise HTTPException(404, "Media asset not found")
    if not db.fetch_one("SELECT id FROM workflow_presets WHERE id = ?", (request.workflow_preset_id,)):
        raise HTTPException(404, "Workflow preset not found")
    await require_comfy_for_image()
    values = request.model_dump(exclude={"workflow_preset_id"})
    if not values.get("prompt"): values["prompt"] = asset["prompt"]
    project = require_project(asset["project_id"])
    head_node_id = asset.get("source_story_node_id") or project.get("active_node_id")
    try:
        template_prompt = values["prompt"]
        values["prompt"], references = expand_image_prompt(db, scheduler.world, asset["project_id"], head_node_id, template_prompt)
    except ImagePromptReferenceError as exc:
        raise HTTPException(422, str(exc)) from exc
    semantic_kind = "background" if asset["kind"] == "location" else asset["kind"]
    full_body_height_factor = None
    if semantic_kind == "full_body":
        entity = scheduler.world.projection(
            asset["project_id"],
            use_cache=False,
        )["entities"].get(asset["entity_id"])
        state = (entity or {}).get("state", {})
        raw_factor = state.get("full_body_height_factor", state.get("height_factor"))
        if raw_factor is not None:
            try:
                full_body_height_factor = max(0.0, min(1.0, float(raw_factor)))
            except (TypeError, ValueError):
                full_body_height_factor = None

    payload = {
        "media_asset_id": asset_id,
        "preset_id": request.workflow_preset_id,
        "values": values,
        "template_prompt": template_prompt,
        "prompt_references": references,
        "image_kind": semantic_kind,
        "full_body_height_factor": full_body_height_factor,
    }
    job = db.create_job(asset["project_id"], "image", payload)
    db.execute("UPDATE entity_media_assets SET status = 'queued', updated_at = ? WHERE id = ?", (utc_now(), asset_id))
    await scheduler.enqueue(job["id"])
    return job


@app.get("/api/music/themes")
async def list_music_themes() -> list[dict[str, Any]]:
    user = current_user()
    if user.admin:
        themes = db.fetch_all("SELECT * FROM music_themes ORDER BY name")
    else:
        themes = db.fetch_all(
            "SELECT DISTINCT t.* FROM music_themes t JOIN project_music_themes pmt ON pmt.theme_id=t.id "
            "JOIN user_project_access a ON a.project_id=pmt.project_id WHERE a.user_id=? ORDER BY t.name",
            (user.id,),
        )
    for theme in themes: theme["tracks"] = db.fetch_all("SELECT * FROM music_tracks WHERE theme_id = ? ORDER BY position, title", (theme["id"],))
    return themes


@app.post("/api/music/themes", status_code=201)
async def create_music_theme(request: MusicThemeCreate) -> dict[str, Any]:
    theme_id, now = new_id(), utc_now()
    try: db.execute("INSERT INTO music_themes(id, name, description, playback_mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (theme_id, request.name.strip(), request.description, request.playback_mode, now, now))
    except Exception as exc: raise HTTPException(409, "A theme with that name already exists") from exc
    result = db.fetch_one("SELECT * FROM music_themes WHERE id = ?", (theme_id,)) or {}
    await events.publish("music", {"theme_id": theme_id, "action": "created"})
    return result


@app.put("/api/music/themes/{theme_id}")
async def update_music_theme(theme_id: str, request: MusicThemeCreate) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM music_themes WHERE id = ?", (theme_id,)):
        raise HTTPException(404, "Theme not found")
    try:
        db.execute("UPDATE music_themes SET name = ?, description = ?, playback_mode = ?, updated_at = ? WHERE id = ?", (request.name.strip(), request.description, request.playback_mode, utc_now(), theme_id))
    except Exception as exc:
        raise HTTPException(409, "A theme with that name already exists") from exc
    result = db.fetch_one("SELECT * FROM music_themes WHERE id = ?", (theme_id,)) or {}
    await events.publish("music", {"theme_id": theme_id, "action": "updated"})
    return result


@app.post("/api/music/themes/{theme_id}/tracks", status_code=201)
async def upload_music_track(theme_id: str, title: str = "", file: UploadFile = File(...)) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM music_themes WHERE id = ?", (theme_id,)): raise HTTPException(404, "Theme not found")
    data = await file.read()
    try: mime, suffix = validate_audio(data, file.filename or "")
    except MediaValidationError as exc: raise HTTPException(422, str(exc)) from exc
    digest = content_hash(data)
    existing = db.fetch_one("SELECT * FROM music_tracks WHERE sha256 = ? ORDER BY created_at LIMIT 1", (digest,))
    duplicate = db.fetch_one("SELECT * FROM music_tracks WHERE sha256 = ? AND theme_id = ?", (digest, theme_id))
    if duplicate: return duplicate
    track_id = new_id()
    path = existing["file_path"] if existing else store_media(db.data_dir, "music", track_id, suffix, data)
    position = (db.fetch_one("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM music_tracks WHERE theme_id = ?", (theme_id,)) or {"n": 0})["n"]
    db.execute("INSERT INTO music_tracks(id, theme_id, title, file_path, mime_type, sha256, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (track_id, theme_id, title.strip() or Path(file.filename or "Track").stem, path, mime, digest, position, utc_now()))
    result = db.fetch_one("SELECT * FROM music_tracks WHERE id = ?", (track_id,)) or {}
    await events.publish("music", {"theme_id": theme_id, "track_id": track_id, "action": "track_added"})
    return result


@app.put("/api/music/tracks/{track_id}")
async def update_music_track(track_id: str, request: MusicTrackUpdate) -> dict[str, Any]:
    track = db.fetch_one("SELECT id, theme_id FROM music_tracks WHERE id = ?", (track_id,))
    if not track:
        raise HTTPException(404, "Track not found")
    db.execute("UPDATE music_tracks SET title = ?, position = ? WHERE id = ?", (request.title.strip(), request.position, track_id))
    result = db.fetch_one("SELECT * FROM music_tracks WHERE id = ?", (track_id,)) or {}
    await events.publish("music", {"theme_id": track["theme_id"], "track_id": track_id, "action": "track_updated"})
    return result


@app.delete("/api/music/tracks/{track_id}", status_code=204)
async def delete_music_track(track_id: str) -> None:
    track = db.fetch_one("SELECT * FROM music_tracks WHERE id = ?", (track_id,))
    if not track: raise HTTPException(404, "Track not found")
    db.execute("DELETE FROM music_tracks WHERE id = ?", (track_id,))
    lifecycle.release_paths([track["file_path"]])
    await events.publish("music", {"theme_id": track["theme_id"], "track_id": track_id, "action": "track_removed"})


@app.delete("/api/music/themes/{theme_id}", status_code=204)
async def delete_music_theme(theme_id: str, remove_references: bool = False) -> None:
    referenced = db.fetch_one("SELECT 1 FROM project_music_themes WHERE theme_id = ?", (theme_id,))
    if referenced and not remove_references: raise HTTPException(409, "Theme is enabled by a project; confirm removal from projects first")
    paths = [row["file_path"] for row in db.fetch_all("SELECT file_path FROM music_tracks WHERE theme_id = ?", (theme_id,))]
    with db._lock, db.connect() as connection:
        if remove_references:
            connection.execute("UPDATE project_music_settings SET manual_theme_id = NULL WHERE manual_theme_id = ?", (theme_id,))
            connection.execute("DELETE FROM project_music_themes WHERE theme_id = ?", (theme_id,))
        connection.execute("DELETE FROM music_tracks WHERE theme_id = ?", (theme_id,))
        connection.execute("DELETE FROM music_themes WHERE id = ?", (theme_id,))
    lifecycle.release_paths(paths)
    await events.publish("music", {"theme_id": theme_id, "action": "removed"})


@app.get("/api/projects/{project_id}/music")
async def get_project_music(project_id: str) -> dict[str, Any]:
    require_project(project_id); settings = db.fetch_one("SELECT * FROM project_music_settings WHERE project_id = ?", (project_id,)) or {"project_id": project_id, "mode": "disabled", "volume": .7, "manual_theme_id": None}
    settings["enabled_theme_ids"] = [row["theme_id"] for row in db.fetch_all("SELECT theme_id FROM project_music_themes WHERE project_id = ?", (project_id,))]
    settings["current_theme_id"] = scheduler.world.projection(project_id).get("current_theme_id")
    playback = db.fetch_one("SELECT theme_id,track_id,revision,updated_by_name_snapshot,updated_at FROM project_music_playback WHERE project_id=?", (project_id,)) or {}
    settings["shared_theme_id"] = playback.get("theme_id")
    settings["current_track_id"] = playback.get("track_id")
    settings["playback_revision"] = playback.get("revision", 0)
    settings["playback_updated_by"] = playback.get("updated_by_name_snapshot")
    return settings


@app.get("/api/projects/{project_id}/music/playback")
async def get_music_playback(project_id: str) -> dict[str, Any]:
    settings = await get_project_music(project_id)
    return {key: settings.get(key) for key in ("shared_theme_id", "current_track_id", "playback_revision", "playback_updated_by")}


@app.put("/api/projects/{project_id}/music/playback")
async def update_music_playback(project_id: str, request: MusicPlaybackUpdate) -> dict[str, Any]:
    require_project(project_id)
    user = current_user()
    settings = db.fetch_one("SELECT mode FROM project_music_settings WHERE project_id=?", (project_id,)) or {"mode": "disabled"}
    if not user.admin and settings["mode"] == "disabled":
        raise HTTPException(403, "Music is disabled for this story")
    if not user.admin and settings["mode"] == "ai_managed":
        current_theme = scheduler.world.projection(project_id).get("current_theme_id")
        if request.theme_id != current_theme:
            raise HTTPException(403, "The storyteller controls theme selection in AI-managed mode")
    allowed = db.fetch_one("SELECT 1 FROM project_music_themes WHERE project_id=? AND theme_id=?", (project_id, request.theme_id))
    track = db.fetch_one("SELECT id,title FROM music_tracks WHERE id=? AND theme_id=?", (request.track_id, request.theme_id))
    theme = db.fetch_one("SELECT id,name FROM music_themes WHERE id=?", (request.theme_id,))
    if not allowed or not track or not theme:
        raise HTTPException(422, "Select an enabled theme and one of its tracks")
    now = utc_now()
    db.execute(
        "INSERT INTO project_music_playback(project_id,theme_id,track_id,revision,updated_by_user_id,updated_by_name_snapshot,updated_at) "
        "VALUES(?,?,?,1,?,?,?) ON CONFLICT(project_id) DO UPDATE SET theme_id=excluded.theme_id,track_id=excluded.track_id,"
        "revision=project_music_playback.revision+1,updated_by_user_id=excluded.updated_by_user_id,updated_by_name_snapshot=excluded.updated_by_name_snapshot,updated_at=excluded.updated_at",
        (project_id, request.theme_id, request.track_id, user.id, user.username, now),
    )
    result = db.fetch_one("SELECT theme_id shared_theme_id,track_id current_track_id,revision playback_revision,updated_by_name_snapshot playback_updated_by,updated_at FROM project_music_playback WHERE project_id=?", (project_id,)) or {}
    await events.publish("music", {"project_id": project_id, "action": "playback_changed", **result, "theme_name": theme["name"], "track_title": track["title"]})
    return result


@app.put("/api/projects/{project_id}/music")
async def update_project_music(project_id: str, request: ProjectMusicUpdate) -> dict[str, Any]:
    require_project(project_id)
    known = {row["id"] for row in db.fetch_all("SELECT id FROM music_themes")}
    if not set(request.enabled_theme_ids).issubset(known) or (request.manual_theme_id and request.manual_theme_id not in request.enabled_theme_ids): raise HTTPException(422, "Music settings reference unavailable themes")
    with db._lock, db.connect() as connection:
        connection.execute("INSERT INTO project_music_settings(project_id, mode, manual_theme_id, volume) VALUES (?, ?, ?, ?) ON CONFLICT(project_id) DO UPDATE SET mode=excluded.mode, manual_theme_id=excluded.manual_theme_id, volume=excluded.volume", (project_id, request.mode, request.manual_theme_id, request.volume))
        connection.execute("DELETE FROM project_music_themes WHERE project_id = ?", (project_id,))
        connection.executemany("INSERT INTO project_music_themes(project_id, theme_id) VALUES (?, ?)", [(project_id, theme_id) for theme_id in request.enabled_theme_ids])
    await events.publish("music", {"project_id": project_id, **request.model_dump()})
    return await get_project_music(project_id)


@app.get("/api/projects/{project_id}/rules")
async def get_rules(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return {
        "stats": [item.model_dump(mode="json") for item in data.rules.stats(project_id)],
        "effects": [item.model_dump(mode="json") for item in data.rules.effects(project_id)],
        "abilities": [item.model_dump(mode="json") for item in data.rules.abilities(project_id)],
        "migration_warnings": data.rules.warnings(project_id),
    }


def _validate_stat_bound_references(
    project_id: str,
    request: StatDefinitionCreate,
    *,
) -> None:
    definitions = {item.stat_key: item for item in data.rules.stats(project_id)}
    for field in ("minimum_stat_key", "maximum_stat_key"):
        key = getattr(request, field)
        if not key:
            continue
        referenced = definitions.get(key)
        if not referenced: raise HTTPException(422, f"{field} references an unknown stat: {key}")
        if not set(request.compatible_owner_kinds).intersection(map(str, referenced.compatible_owner_kinds)):
            raise HTTPException(422, f"{field} has no compatible owner kind in common with {request.stat_key}")
    graph = {key: [candidate for candidate in (item.minimum_stat_key, item.maximum_stat_key) if candidate] for key, item in definitions.items()}
    graph[request.stat_key] = [candidate for candidate in (request.minimum_stat_key, request.maximum_stat_key) if candidate]
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(key: str) -> None:
        if key in visiting: raise HTTPException(422, "Stat bound dependencies contain a cycle")
        if key in visited: return
        visiting.add(key)
        for child in graph.get(key, []): visit(child)
        visiting.remove(key); visited.add(key)
    for key in graph: visit(key)


@app.post("/api/projects/{project_id}/stats", status_code=201)
async def create_stat(project_id: str, request: StatDefinitionCreate) -> dict[str, Any]:
    require_project(project_id)
    _validate_stat_bound_references(project_id, request)
    try:
        result = data.rules.save_stat(Stat.model_validate({"project_id": project_id, **request.model_dump()}))
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/api/projects/{project_id}/stats/adjust")
async def manually_adjust_stat(project_id: str, request: StatAdjustmentRequest) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutation = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "adjustStat", "arguments": request.model_dump(exclude_none=True)}], provenance="author")
        transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutation, provenance="author", summary=f"Corrected {request.stat_key}") if project.get("active_node_id") else scheduler.world.commit_root(project_id, mutation, provenance="author", summary=f"Corrected {request.stat_key}")
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("stats", {"project_id": project_id, "transaction_id": transaction["id"], "stat_key": request.stat_key})
    return {"transaction": transaction, "world": await get_world(project_id)}


@app.put("/api/projects/{project_id}/stats/{stat_key}")
async def update_stat(project_id: str, stat_key: str, request: StatDefinitionCreate) -> dict[str, Any]:
    if not data.rules.stat(project_id, stat_key):
        raise HTTPException(404, "Stat definition not found")
    if request.stat_key != stat_key: raise HTTPException(422, "stat_key is immutable")
    _validate_stat_bound_references(project_id, request)
    try:
        result = data.rules.save_stat(Stat.model_validate({"project_id": project_id, **request.model_dump()}), previous_key=stat_key)
    except Exception as exc:
        raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/api/projects/{project_id}/effects", status_code=201)
async def create_effect(project_id: str, request: EffectDefinitionCreate) -> dict[str, Any]:
    require_project(project_id)
    if not data.rules.stat(project_id, request.target_stat_key): raise HTTPException(422, "Unknown target stat")
    _validate_formula_stats(project_id, request.formula)
    try: result = data.rules.save_effect(EffectDefinition.model_validate({"project_id": project_id, **request.model_dump()}))
    except Exception as exc: raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


@app.put("/api/projects/{project_id}/effects/{effect_key}")
async def update_effect(project_id: str, effect_key: str, request: EffectDefinitionCreate) -> dict[str, Any]:
    if not data.rules.effect(project_id, effect_key): raise HTTPException(404, "Effect definition not found")
    if request.effect_key != effect_key: raise HTTPException(422, "effect_key is immutable")
    if not data.rules.stat(project_id, request.target_stat_key): raise HTTPException(422, "Unknown target stat")
    _validate_formula_stats(project_id, request.formula)
    try: result = data.rules.save_effect(EffectDefinition.model_validate({"project_id": project_id, **request.model_dump()}), previous_key=effect_key)
    except Exception as exc: raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


def _validate_formula_stats(project_id: str, node: Any) -> None:
    if str(node.kind) == "stat" and not data.rules.stat(project_id, str(node.stat_key)):
        raise HTTPException(422, f"Formula references unknown stat: {node.stat_key}")
    for child in node.children: _validate_formula_stats(project_id, child)


@app.post("/api/projects/{project_id}/abilities", status_code=201)
async def create_ability(project_id: str, request: AbilityDefinitionCreate) -> dict[str, Any]:
    require_project(project_id)
    known_bullet_skills = {row["id"] for row in scheduler.minigames.bullethell.catalog()["skills"]}
    if not set(request.bullethell_skill_ids) <= known_bullet_skills:
        raise HTTPException(422, "Ability references an unavailable bullet-hell skill")
    if request.timed_attack_line_count is not None:
        config = next(row for row in scheduler.minigames.configs(project_id) if row["game_key"] == "timed_attack")
        if not (config["min_attack_lines"] <= request.timed_attack_line_count <= config["max_attack_lines"] and config["min_attack_damage"] <= request.timed_attack_damage_per_line <= config["max_attack_damage"]):
            raise HTTPException(422, "Timed-attack ability profile is outside the project minigame ranges")
    for cost in request.costs:
        if cost.stat_key and not data.rules.stat(project_id, cost.stat_key): raise HTTPException(422, f"Unknown stat in ability: {cost.stat_key}")
    for action in request.actions:
        if action.effect_key and not data.rules.effect(project_id, action.effect_key): raise HTTPException(422, f"Unknown effect in ability: {action.effect_key}")
    try: result = data.rules.save_ability(Ability.model_validate({"project_id": project_id, **request.model_dump(), "requirements": RequirementExpression.model_validate(request.requirements)}))
    except Exception as exc: raise HTTPException(422, str(exc)) from exc
    return result.model_dump(mode="json")


@app.put("/api/projects/{project_id}/abilities/{ability_key}")
async def update_ability(project_id: str, ability_key: str, request: AbilityDefinitionCreate) -> dict[str, Any]:
    if not data.rules.ability(project_id, ability_key): raise HTTPException(404, "Ability definition not found")
    if request.ability_key != ability_key: raise HTTPException(422, "ability_key is immutable")
    return await create_ability(project_id, request)


@app.post("/api/projects/{project_id}/abilities/use")
async def use_ability(project_id: str, request: AbilityUseRequest) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "useAbility", "arguments": request.model_dump(exclude_none=True)}], provenance="player")
        transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="player", summary=f"Used {request.ability_key}") if project.get("active_node_id") else scheduler.world.commit_root(project_id, mutations, provenance="player", summary=f"Used {request.ability_key}")
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc
    return {"transaction": transaction}


@app.delete("/api/projects/{project_id}/stats/{stat_key}", status_code=204)
async def delete_stat(project_id: str, stat_key: str) -> None:
    require_idle_project(project_id)
    definition = data.rules.stat(project_id, stat_key)
    if not definition: raise HTTPException(404, "Stat definition not found")
    referenced_bound = db.fetch_one(
        "SELECT stat_key,label FROM stat_definitions WHERE project_id=? AND stat_key<>? AND (minimum_stat_key=? OR maximum_stat_key=?) LIMIT 1",
        (project_id, stat_key, stat_key, stat_key),
    )
    if referenced_bound: raise HTTPException(409, f"Stat is used as a bound by {referenced_bound['label']}")
    if db.fetch_one("SELECT 1 FROM effect_definitions WHERE project_id=? AND target_stat_key=?", (project_id, stat_key)): raise HTTPException(409, "Stat is targeted by an effect")
    if db.fetch_one("SELECT 1 FROM effect_formula_nodes WHERE project_id=? AND stat_key=?", (project_id, stat_key)): raise HTTPException(409, "Stat is referenced by an effect formula")
    if db.fetch_one("SELECT 1 FROM ability_costs WHERE project_id=? AND stat_key=?", (project_id, stat_key)): raise HTTPException(409, "Stat is referenced by an ability cost")
    if db.fetch_one("SELECT 1 FROM ability_requirement_nodes WHERE project_id=? AND stat_key=?", (project_id, stat_key)): raise HTTPException(409, "Stat is referenced by an ability requirement")
    if db.fetch_one("SELECT 1 FROM ability_passive_triggers WHERE project_id=? AND stat_key=?", (project_id, stat_key)): raise HTTPException(409, "Stat is referenced by a passive trigger")
    db.execute("DELETE FROM stat_definitions WHERE project_id=? AND stat_key=?", (project_id, stat_key))


@app.delete("/api/projects/{project_id}/effects/{effect_key}", status_code=204)
async def delete_effect(project_id: str, effect_key: str) -> None:
    require_idle_project(project_id)
    if db.fetch_one("SELECT 1 FROM ability_actions WHERE project_id=? AND effect_key=?", (project_id, effect_key)): raise HTTPException(409, "Effect is referenced by an ability")
    if any(item.get("effect_key") == effect_key for item in scheduler.world.projection(project_id).get("active_effects", {}).values()): raise HTTPException(409, "Effect has active instances")
    db.execute("DELETE FROM effect_definitions WHERE project_id=? AND effect_key=?", (project_id, effect_key))


@app.post("/api/projects/{project_id}/effects/apply")
async def apply_effect(project_id: str, request: ApplyEffectRequest) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "applyEffect", "arguments": request.model_dump(exclude_none=True)}], provenance="author")
        transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary=f"Applied {request.effect_key}") if project.get("active_node_id") else scheduler.world.commit_root(project_id, mutations, provenance="author", summary=f"Applied {request.effect_key}")
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc
    return {"transaction": transaction}


@app.delete("/api/projects/{project_id}/effects/active/{instance_id}")
async def remove_active_effect(project_id: str, instance_id: str) -> dict[str, Any]:
    project = require_project(project_id)
    try:
        mutations = scheduler.world.normalize_mutations(project_id, project.get("active_node_id"), [{"tool": "removeEffect", "arguments": {"active_instance_id": instance_id}}], provenance="author")
        transaction = scheduler.world.commit_to_existing_node(project_id, project["active_node_id"], mutations, provenance="author", summary="Removed active effect") if project.get("active_node_id") else scheduler.world.commit_root(project_id, mutations, provenance="author", summary="Removed active effect")
    except WorldValidationError as exc: raise HTTPException(422, str(exc)) from exc
    return {"transaction": transaction}


@app.delete("/api/projects/{project_id}/abilities/{ability_key}", status_code=204)
async def delete_ability(project_id: str, ability_key: str) -> None:
    require_idle_project(project_id)
    if db.fetch_one("SELECT 1 FROM ability_requirement_nodes WHERE project_id=? AND required_ability_key=?", (project_id, ability_key)): raise HTTPException(409, "Ability is referenced by another ability requirement")
    if db.fetch_one("SELECT 1 FROM world_events WHERE project_id=? AND payload_json LIKE ? LIMIT 1", (project_id, f'%"{ability_key}"%')): raise HTTPException(409, "Ability is referenced by world state or history")
    db.execute("DELETE FROM ability_definitions WHERE ability_key = ? AND project_id = ?", (ability_key, project_id))


@app.post("/api/projects/{project_id}/rules/migration-warnings/{warning_id}/acknowledge")
async def acknowledge_rule_warning(project_id: str, warning_id: str) -> dict[str, bool]:
    require_project(project_id)
    db.execute("UPDATE rule_migration_warnings SET acknowledged=1 WHERE id=? AND project_id=?", (warning_id, project_id))
    return {"acknowledged": True}


@app.get("/api/projects/{project_id}/map/nearby")
async def nearby_locations(project_id: str, origin_id: str, direction: str | None = None, head_node_id: str | None = None):
    try:
        return scheduler.world.nearby(project_id, origin_id, head_node_id=head_node_id, direction=direction)
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/projects/{project_id}/map/route")
async def find_world_route(project_id: str, source_id: str, target_id: str, mode: str | None = None, head_node_id: str | None = None):
    try:
        route = scheduler.world.route(project_id, source_id, target_id, head_node_id=head_node_id, mode=mode)
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if route is None:
        raise HTTPException(404, "No traversable route found")
    return route


@app.get("/api/projects/{project_id}/bible-import")
async def preview_bible_import(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    documents = db.fetch_all(
        "SELECT * FROM bible_documents WHERE project_id = ? AND trim(content) != '' ORDER BY position", (project_id,)
    )
    existing_names = {entity["name"] for entity in scheduler.world.projection(project_id)["entities"].values()}
    items = [
        {"kind": "lore_system" if document["kind"] in {"style", "world"} else "fact",
         "name": f"Story Bible: {document['title']}", "aliases": [document["title"]], "tags": ["story_bible", document["kind"]],
         "state": {"summary": document["content"], "visibility": "narrator"}}
        for document in documents if f"Story Bible: {document['title']}" not in existing_names
    ]
    return {"items": items}


@app.post("/api/projects/{project_id}/bible-import")
async def import_bible(project_id: str) -> dict[str, Any]:
    preview = await preview_bible_import(project_id)
    if not preview["items"]:
        return {"imported": 0}
    mutations = scheduler.world.normalize_mutations(
        project_id, None, [{"tool": "createEntity", "arguments": item} for item in preview["items"]], provenance="author"
    )
    transaction = scheduler.world.commit_root(project_id, mutations, provenance="bible_import", summary="Imported story bible")
    await events.publish("memory_changed", {"project_id": project_id, "transaction_id": transaction["id"]})
    return {"imported": len(mutations), "transaction_id": transaction["id"]}


@app.post("/api/projects/{project_id}/planning", status_code=201)
async def create_planning_session(project_id: str, request: PlanningSessionCreate) -> dict[str, Any]:
    require_project(project_id)
    return generation_api.workspace.create(project_id, request.model_dump())




@app.get("/api/projects/{project_id}/generation-plans")
async def list_generation_plans(project_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    return generation_api.list_project(project_id)


@app.get("/api/generation-plans/{plan_id}")
async def get_generation_plan(plan_id: str) -> dict[str, Any]:
    try:
        return generation_api.get(plan_id)
    except GenerationPlanError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/generation-plans/{plan_id}/tasks", status_code=201)
async def create_generation_plan_task(plan_id: str, request: GenerationPlanTaskCreate) -> dict[str, Any]:
    try:
        return generation_api.batch.create_task(plan_id, request.model_dump())
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch("/api/generation-plans/{plan_id}/tasks/{task_key}")
async def update_generation_plan_task(plan_id: str, task_key: str, request: GenerationPlanTaskUpdate) -> dict[str, Any]:
    try:
        patch = request.model_dump(exclude_unset=True)
        patch = {
            key: value for key, value in patch.items()
            if value is not None or key == "target_key"
        }
        return generation_api.batch.update_task(plan_id, task_key, patch)
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.put("/api/generation-plans/{plan_id}/tasks/{task_key}/dependencies")
async def update_generation_plan_dependencies(plan_id: str, task_key: str, request: GenerationDependenciesUpdate) -> dict[str, Any]:
    try:
        return generation_api.batch.replace_dependencies(plan_id, task_key, [item.model_dump() for item in request.dependencies])
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.delete("/api/generation-plans/{plan_id}/tasks/{task_key}")
async def delete_generation_plan_task(plan_id: str, task_key: str) -> dict[str, Any]:
    try:
        return generation_api.batch.delete_task(plan_id, task_key)
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/projects/{project_id}/generation-plans/random-direction", status_code=202)
async def generation_plan_random_direction(
    project_id: str,
    request: RandomPlanningDirectionRequest,
) -> dict[str, Any]:
    require_project(project_id)
    user = current_user()
    job = batch_api.queue_random_direction(
        project_id,
        request.theme.strip(),
        requested_by_user_id=user.id,
        requester_name_snapshot=user.username,
    )
    await scheduler.enqueue(job["id"])
    return job


@app.post("/api/generation-plans/planning/{session_id}")
async def import_planning_generation_plan(session_id: str) -> dict[str, Any]:
    try:
        return generation_api.planning_plan(session_id)
    except (GenerationPlanError, WorldValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post(
    "/api/generation-plans/planning/{session_id}/tasks/{task_number}/generate",
    status_code=202,
)
async def generate_generation_plan_planning_task(
    session_id: str,
    task_number: int,
    request: GenerationTaskGenerateRequest | None = None,
) -> dict[str, Any]:
    request = request or GenerationTaskGenerateRequest()
    user = current_user()
    try:
        result = generation_api.queue_planning_task(
            session_id,
            task_number,
            human_prompt=request.prompt.strip(),
            repair=request.repair,
            append=request.append,
            focus=request.focus.strip() if request.focus else None,
            automate=request.automate,
            automation_prompt=request.automation_prompt.strip(),
            requested_by_user_id=user.id,
            requester_name_snapshot=user.username,
        )
    except (GenerationPlanError, WorldValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    if result.get("deterministic"):
        return result

    await scheduler.enqueue(result["job"]["id"])
    return result


@app.put(
    "/api/generation-plans/planning/{session_id}/tasks/{task_number}/result"
)
async def save_generation_plan_planning_result(
    session_id: str,
    task_number: int,
    request: PlanningDraftUpdate,
) -> dict[str, Any]:
    try:
        return generation_api.save_planning_result(
            session_id,
            task_number,
            request.draft,
        )
    except (GenerationPlanError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post(
    "/api/generation-plans/planning/{session_id}/tasks/{task_number}/preflight"
)
async def preflight_generation_plan_planning_task(
    session_id: str,
    task_number: int,
    request: PlanningDraftUpdate,
) -> dict[str, Any]:
    try:
        return {
            "conflicts": generation_api.preflight_planning(
                session_id,
                task_number,
                request.draft,
            )
        }
    except WorldValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post(
    "/api/generation-plans/planning/{session_id}/tasks/{task_number}/approve"
)
async def approve_generation_plan_planning_task(
    session_id: str,
    task_number: int,
    request: PlanningApprovalRequest,
) -> dict[str, Any]:
    try:
        plan = generation_api.approve_and_commit_planning(
            session_id,
            task_number,
            draft=request.draft,
            resolutions={
                key: value.model_dump(exclude_none=True)
                for key, value in request.resolutions.items()
            },
        )
    except (GenerationPlanError, WorldValidationError, ValueError) as exc:
        status = 409 if "conflict" in str(exc).casefold() else 422
        raise HTTPException(status, str(exc)) from exc

    await events.publish(
        "planning",
        {
            "session_id": session_id,
            "task_number": task_number,
            "status": "approved",
        },
    )
    return plan


@app.post("/api/generation-plans/{plan_id}/tasks/{task_key}/generate", status_code=202)
async def generate_generation_plan_task(
    plan_id: str,
    task_key: str,
) -> dict[str, Any]:
    user = current_user()
    try:
        job = generation_api.batch.queue_task(
            plan_id,
            task_key,
            requested_by_user_id=user.id,
            requester_name_snapshot=user.username,
        )
    except GenerationPlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    await scheduler.enqueue(job["id"])
    return job


@app.post("/api/generation-plans/{plan_id}/generate-ready", status_code=202)
async def generate_ready_generation_plan_tasks(
    plan_id: str,
) -> dict[str, Any]:
    user = current_user()
    try:
        jobs = generation_api.batch.queue_ready(
            plan_id,
            requested_by_user_id=user.id,
            requester_name_snapshot=user.username,
        )
    except GenerationPlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    for job in jobs:
        await scheduler.enqueue(job["id"])
    return {"jobs": jobs, "plan": generation_api.get(plan_id)}


@app.put("/api/generation-plans/{plan_id}/tasks/{task_key}/result")
async def replace_generation_plan_task_result(
    plan_id: str,
    task_key: str,
    request: GenerationResultUpdate,
) -> dict[str, Any]:
    try:
        return generation_api.replace_generated_result(
            plan_id,
            task_key,
            request.result,
        )
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/generation-plans/{plan_id}/tasks/{task_key}/approve")
async def approve_generation_plan_task(
    plan_id: str,
    task_key: str,
    request: GenerationTaskReviewRequest,
) -> dict[str, Any]:
    try:
        if request.result is not None:
            generation_api.replace_generated_result(
                plan_id,
                task_key,
                request.result,
            )
        return generation_api.approve(
            plan_id,
            task_key,
            request.note,
        )
    except (GenerationPlanError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/generation-plans/{plan_id}/tasks/{task_key}/reject")
async def reject_generation_plan_task(
    plan_id: str,
    task_key: str,
    request: GenerationTaskRejectRequest,
) -> dict[str, Any]:
    try:
        return generation_api.reject(
            plan_id,
            task_key,
            request.note,
        )
    except GenerationPlanError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/generation-plans/{plan_id}/tasks/{task_key}/revisions")
async def generation_plan_task_revisions(
    plan_id: str,
    task_key: str,
) -> list[dict[str, Any]]:
    return generation_api.revisions(plan_id, task_key)


@app.get("/api/projects/{project_id}/story-defaults")
async def get_project_story_defaults(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    return db.fetch_one("SELECT * FROM project_story_defaults WHERE project_id=?", (project_id,)) or {}


@app.put("/api/projects/{project_id}/story-defaults")
async def update_project_story_defaults(project_id: str, request: ProjectStoryDefaultsUpdate) -> dict[str, Any]:
    require_project(project_id)
    if request.pov_character_id:
        entity = scheduler.world.projection(project_id)["entities"].get(request.pov_character_id)
        if not entity or entity.get("kind") != "character" or not entity.get("state", {}).get("player_controlled"):
            raise HTTPException(422, "Default POV must be a playable character")
    db.execute("INSERT INTO project_story_defaults(project_id,narration_mode,pov_strategy,pov_character_id,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET narration_mode=excluded.narration_mode,pov_strategy=excluded.pov_strategy,pov_character_id=excluded.pov_character_id,updated_at=excluded.updated_at", (project_id, request.narration_mode, request.pov_strategy, request.pov_character_id, utc_now()))
    return await get_project_story_defaults(project_id)


@app.get("/api/projects/{project_id}/planning")
async def get_planning_session(project_id: str) -> dict[str, Any] | None:
    require_project(project_id)
    plan_id = generation_api.workspace.latest_plan_id(project_id)
    return generation_api.workspace.view(plan_id) if plan_id else None








@app.post("/api/planning/{session_id}/tasks/{task_number}/reopen")
async def reopen_planning_stage(session_id: str, task_number: int) -> dict[str, Any]:
    try:
        result = generation_api.workspace.reopen(session_id, task_number)
    except (GenerationPlanError, WorldValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("planning", {"session_id": session_id, "task_number": task_number, "status": "ready"})
    return result


@app.post("/api/planning/{session_id}/tasks/{task_number}/skip")
async def skip_planning_stage(session_id: str, task_number: int) -> dict[str, Any]:
    try:
        result = generation_api.workspace.skip(session_id, task_number)
    except (GenerationPlanError, WorldValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("planning", {"session_id": session_id, "task_number": task_number, "status": "skipped"})
    return result


@app.post("/api/planning/{session_id}/tasks/{task_number}/revalidate")
async def revalidate_planning_stage(session_id: str, task_number: int) -> dict[str, Any]:
    try:
        result = generation_api.workspace.revalidate(session_id, task_number)
    except (GenerationPlanError, WorldValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    await events.publish("planning", {"session_id": session_id, "task_number": task_number, "status": "approved"})
    return result


@app.get("/api/planning/{session_id}/tasks/{task_number}/dependency-impact")
async def planning_dependency_impact(session_id: str, task_number: int) -> dict[str, Any]:
    try:
        return generation_api.workspace.dependency_impact(session_id, task_number)
    except GenerationPlanError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/planning/{session_id}/revisions")
async def planning_revision_history(session_id: str) -> list[dict[str, Any]]:
    try:
        return generation_api.workspace.revisions(session_id)
    except GenerationPlanError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.patch("/api/planning/image-plans/{plan_id}")
async def update_planning_image_plan(
    plan_id: str,
    request: PlanningImagePlanUpdate,
) -> dict[str, Any]:
    plan = generation_api.workspace.image_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Planning image not found")
    if plan["status"] == "queued":
        raise HTTPException(409, "Wait for or cancel the active image job")
    workflow = (
        data.workflows.get(request.workflow_preset_id)
        if request.workflow_preset_id
        else None
    )
    status = (
        "ready"
        if workflow and workflow["validation_status"] == "valid"
        else "draft"
    )
    revision = hashlib.sha256(
        json.dumps(
            request.model_dump(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return generation_api.workspace.update_image_plan(
        plan_id,
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        workflow_preset_id=request.workflow_preset_id,
        width=request.width,
        height=request.height,
        prompt_revision=revision,
        status=status,
    )


@app.delete("/api/planning/image-plans/{plan_id}", status_code=204)
async def delete_planning_image_plan(plan_id: str) -> None:
    plan = generation_api.workspace.image_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Planning image not found")
    if plan["status"] == "queued":
        raise HTTPException(409, "Wait for or cancel the active image job")
    generation_api.workspace.delete_image_plan(plan_id)


async def _queue_planning_image(plan_id: str) -> dict[str, Any]:
    plan = db.fetch_one("SELECT * FROM generation_image_plans WHERE id=?", (plan_id,))
    if not plan: raise HTTPException(404, "Planning image not found")
    if plan["status"] == "queued" and plan.get("generation_job_id"):
        job = db.get_job(plan["generation_job_id"])
        if job and job["status"] in {"queued", "running", "switching"}: return job
    if plan["status"] == "generated" and plan.get("generation_job_id"):
        job = db.get_job(plan["generation_job_id"])
        if job and job["status"] == "succeeded":
            return {**job, "duplicate": True}
    workflow = db.fetch_one("SELECT id,validation_status FROM workflow_presets WHERE id=?", (plan.get("workflow_preset_id"),))
    if not workflow or workflow["validation_status"] != "valid": raise HTTPException(422, "Select a valid workflow before generating")
    asset = db.fetch_one("SELECT * FROM entity_media_assets WHERE entity_id=? AND kind=? AND COALESCE(outfit_id,'')=COALESCE(?, '') AND featured=1", (plan["entity_id"], plan["kind"], plan.get("outfit_id")))
    now = utc_now()
    if asset:
        asset_id = asset["id"]; db.execute("UPDATE entity_media_assets SET prompt=?,negative_prompt=?,status='suggested',updated_at=? WHERE id=?", (plan["prompt"], plan["negative_prompt"], now, asset_id))
    else:
        asset_id = new_id(); db.execute("INSERT INTO entity_media_assets(id,project_id,entity_id,outfit_id,kind,source,status,prompt,negative_prompt,featured,created_at,updated_at) VALUES(?,?,?,?,?,'suggested','suggested',?,?,1,?,?)", (asset_id, plan["project_id"], plan["entity_id"], plan.get("outfit_id"), plan["kind"], plan["prompt"], plan["negative_prompt"], now, now))
        if plan["kind"] == "location": db.execute("INSERT OR IGNORE INTO location_backgrounds(id,project_id,location_id,media_asset_id,position,created_at) VALUES(?,?,?,?,0,?)", (new_id(), plan["project_id"], plan["entity_id"], asset_id, now))
    job = await generate_entity_media(asset_id, ImageGenerateRequest(workflow_preset_id=plan["workflow_preset_id"], prompt=plan["prompt"], negative_prompt=plan["negative_prompt"], width=plan.get("width"), height=plan.get("height")))
    payload = job.get("payload") or {}
    payload["planning_image_plan_id"] = plan_id
    db.execute("UPDATE generation_jobs SET payload_json=? WHERE id=?", (json.dumps(payload), job["id"]))
    generation_api.workspace.mark_image_plan_queued(plan_id, media_asset_id=asset_id, generation_job_id=job["id"])
    return job


@app.post("/api/planning/image-plans/{plan_id}/generate", status_code=202)
async def generate_planning_image_plan(plan_id: str) -> dict[str, Any]:
    return await _queue_planning_image(plan_id)


@app.post("/api/planning/{session_id}/images/generate", status_code=202)
async def generate_planning_images(
    session_id: str,
    request: PlanningImageGenerateBatch,
) -> dict[str, Any]:
    try:
        generation_api.workspace.plan(session_id)
    except GenerationPlanError as exc:
        raise HTTPException(404, str(exc)) from exc
    ids = request.plan_ids or generation_api.workspace.ready_image_plan_ids(session_id)
    known = generation_api.workspace.image_plan_ids(session_id)
    if not set(ids) <= known:
        raise HTTPException(
            422,
            "Image selection contains a plan from another workshop",
        )
    jobs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for plan_id in dict.fromkeys(ids):
        try:
            jobs.append(await _queue_planning_image(plan_id))
        except HTTPException as exc:
            failures.append({"plan_id": plan_id, "error": str(exc.detail)})
    return {"jobs": jobs, "failures": failures}


@app.post("/api/planning/{session_id}/tasks/{task_number}/reset")
async def reset_planning_stage(session_id: str, task_number: int) -> dict[str, Any]:
    try:
        return generation_api.workspace.reopen(session_id, task_number)
    except GenerationPlanError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/planning/{session_id}/delete-impact")
async def planning_delete_impact(session_id: str) -> dict[str, Any]:
    try:
        plan = generation_api.workspace.plan(session_id)
    except GenerationPlanError as exc:
        raise HTTPException(404, str(exc)) from exc
    tx_ids = [
        str((task.get("commit_metadata") or {}).get("transaction_id"))
        for task in plan["tasks"]
        if (task.get("commit_metadata") or {}).get("transaction_id")
    ]
    tx_ids = list(dict.fromkeys(tx_ids))
    placeholders = ",".join("?" for _ in tx_ids)
    entities = relations = lore = 0
    if tx_ids:
        entities = int((db.fetch_one(
            f"SELECT COUNT(DISTINCT entity_id) n FROM world_events "
            f"WHERE transaction_id IN ({placeholders}) AND entity_id IS NOT NULL",
            tx_ids,
        ) or {"n": 0})["n"])
        relations = int((db.fetch_one(
            f"SELECT COUNT(*) n FROM world_events "
            f"WHERE transaction_id IN ({placeholders}) AND event_type LIKE 'relationship.%'",
            tx_ids,
        ) or {"n": 0})["n"])
        lore = int((db.fetch_one(
            f"SELECT COUNT(*) n FROM lore_card_versions "
            f"WHERE transaction_id IN ({placeholders})",
            tx_ids,
        ) or {"n": 0})["n"])
    return {
        "session_id": session_id,
        "confirmation": "DELETE PLANNING",
        "ambiguous": False,
        "counts": {
            "transactions": len(tx_ids),
            "entities": entities,
            "relations": relations,
            "lore_versions": lore,
        },
        "transaction_ids": tx_ids,
    }


@app.delete("/api/planning/{session_id}")
async def delete_planning_session(session_id: str, request: PlanningDeleteRequest) -> dict[str, Any]:
    impact = await planning_delete_impact(session_id)
    if request.confirmation != impact["confirmation"]:
        raise HTTPException(422, f"Type {impact['confirmation']} to confirm")
    plan = generation_api.workspace.plan(session_id)
    try:
        lifecycle.require_idle(plan["project_id"])
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc
    tx_ids = impact["transaction_ids"]
    with db._lock, db.connect() as connection:
        if request.mode == "remove_world" and tx_ids:
            placeholders = ",".join("?" for _ in tx_ids)
            version_ids = [
                row["id"]
                for row in connection.execute(
                    f"SELECT id FROM lore_card_versions WHERE transaction_id IN ({placeholders})",
                    tx_ids,
                )
            ]
            if version_ids:
                version_placeholders = ",".join("?" for _ in version_ids)
                connection.execute(
                    f"DELETE FROM lore_card_search WHERE version_id IN ({version_placeholders})",
                    version_ids,
                )
            connection.execute(
                f"DELETE FROM world_transactions WHERE id IN ({placeholders})",
                tx_ids,
            )
            connection.execute(
                "DELETE FROM world_entities WHERE project_id=? "
                "AND id NOT IN (SELECT DISTINCT entity_id FROM world_events WHERE entity_id IS NOT NULL)",
                (plan["project_id"],),
            )
        connection.execute("DELETE FROM generation_plans WHERE id=?", (session_id,))
        connection.execute(
            "DELETE FROM world_projection_cache WHERE project_id=?",
            (plan["project_id"],),
        )
    return {"deleted": True, "mode": request.mode, "impact": impact}


@app.delete("/api/planning/{session_id}/revisions")
async def clear_planning_revisions(session_id: str) -> dict[str, int]:
    try:
        return {"removed": generation_api.workspace.clear_revisions(session_id)}
    except GenerationPlanError as exc:
        raise HTTPException(404, str(exc)) from exc



@app.get("/api/projects/{project_id}/reviews")
async def list_pending_reviews(project_id: str) -> list[dict[str, Any]]:
    require_project(project_id)
    rows = db.fetch_all(
        "SELECT r.* FROM pending_reviews r JOIN generation_jobs j ON j.id = r.job_id "
        "WHERE j.project_id = ? AND r.status = 'pending' ORDER BY r.created_at", (project_id,),
    )
    for row in rows:
        row["mutations"] = json.loads(row.pop("mutations_json"))
    return rows


@app.post("/api/reviews/{review_id}")
async def decide_review(review_id: str, request: ReviewDecision) -> dict[str, Any]:
    review = db.fetch_one("SELECT * FROM pending_reviews WHERE id = ? AND status = 'pending'", (review_id,))
    if not review:
        raise HTTPException(404, "Pending review not found")
    job = db.get_job(review["job_id"])
    if not job:
        raise HTTPException(404, "Generation job not found")
    stored = request.mutations if request.mutations is not None else json.loads(review["mutations_json"])
    raw = [{"tool": item["tool"], "arguments": item.get("arguments", {})} for item in stored]
    now = utc_now()
    if review["phase"] == "pre_prose":
        if request.action == "approve":
            payload = job["payload"]
            payload["approved_mutations"] = raw
            db.update_job_payload(job["id"], payload)
            db.execute("UPDATE pending_reviews SET status = 'approved', updated_at = ? WHERE id = ?", (now, review_id))
            await scheduler.enqueue(job["id"])
            return {"status": "resumed", "job_id": job["id"]}
        if request.action == "reject_replan":
            payload = job["payload"]
            payload.pop("approved_mutations", None)
            payload["replan_feedback"] = request.feedback
            db.update_job_payload(job["id"], payload)
            db.execute("UPDATE pending_reviews SET status = 'rejected', updated_at = ? WHERE id = ?", (now, review_id))
            await scheduler.enqueue(job["id"])
            return {"status": "replanning", "job_id": job["id"]}
        raise HTTPException(400, "Pre-prose reviews support approve or reject_replan")
    story_node_id = review["story_node_id"]
    if request.action == "accept_reconciliation":
        mutations = scheduler.world.normalize_mutations(job["project_id"], story_node_id, raw)
        transaction = scheduler.world.commit_to_existing_node(
            job["project_id"], story_node_id, mutations, provenance="approved_reconciliation", summary="Approved major reconciliation"
        )
        db.execute("UPDATE story_nodes SET status = 'complete' WHERE id = ?", (story_node_id,))
        db.execute("UPDATE pending_reviews SET status = 'approved', updated_at = ? WHERE id = ?", (now, review_id))
        db.update_job(job["id"], "completed", result=job.get("result"))
        await events.publish("memory_changed", {"job_id": job["id"], "transaction_id": transaction["id"]})
        return {"status": "accepted", "transaction_id": transaction["id"]}
    if request.action == "reject_regenerate":
        node = require_node(story_node_id)
        user_node_id = node["parent_id"]
        db.execute("UPDATE story_nodes SET status = 'rejected' WHERE id = ?", (story_node_id,))
        db.execute("UPDATE projects SET active_node_id = ?, updated_at = ? WHERE id = ?", (user_node_id, now, job["project_id"]))
        db.execute("UPDATE pending_reviews SET status = 'rejected', updated_at = ? WHERE id = ?", (now, review_id))
        db.update_job(job["id"], "rejected")
        payload = dict(job["payload"])
        payload.pop("approved_mutations", None)
        payload["replan_feedback"] = request.feedback
        new_job = db.create_job(job["project_id"], "story", payload)
        await scheduler.enqueue(new_job["id"])
        return {"status": "regenerating", "job": new_job}
    raise HTTPException(400, "Reconciliation reviews support accept_reconciliation or reject_regenerate")


@app.patch("/api/suggestions/{suggestion_id}")
async def update_suggestion(suggestion_id: str, request: ImageSuggestionUpdate) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM image_suggestions WHERE id = ?", (suggestion_id,)):
        raise HTTPException(404, "Illustration suggestion not found")
    db.execute(
        "UPDATE image_suggestions SET title = ?, prompt = ?, negative_prompt = ?, updated_at = ? WHERE id = ?",
        (request.title.strip(), request.prompt.strip(), request.negative_prompt, utc_now(), suggestion_id),
    )
    return db.fetch_one("SELECT * FROM image_suggestions WHERE id = ?", (suggestion_id,)) or {}


@app.delete("/api/suggestions/{suggestion_id}", status_code=204)
async def delete_suggestion(suggestion_id: str) -> None:
    suggestion = db.fetch_one(
        "SELECT s.*,n.project_id FROM image_suggestions s JOIN story_nodes n ON n.id=s.story_node_id WHERE s.id=?", (suggestion_id,)
    )
    if not suggestion:
        raise HTTPException(404, "Illustration suggestion not found")
    active = db.fetch_one(
        "SELECT id FROM generation_jobs WHERE status IN ('queued','running','switching') "
        "AND json_extract(payload_json,'$.suggestion_id')=? LIMIT 1", (suggestion_id,),
    )
    if active:
        raise HTTPException(409, {
            "message": "This illustration is currently generating. Cancel that image operation before deleting it.",
            "job_id": active["id"], "recovery_actions": ["cancel_image_job", "retry_delete"],
        })
    db.execute("DELETE FROM image_suggestions WHERE id=?", (suggestion_id,))
    lifecycle.release_paths([suggestion.get("image_path")])


@app.get("/api/suggestions/{suggestion_id}/delete-impact")
async def suggestion_delete_impact(suggestion_id: str) -> dict[str, Any]:
    suggestion = db.fetch_one("SELECT * FROM image_suggestions WHERE id=?", (suggestion_id,))
    if not suggestion:
        raise HTTPException(404, "Illustration suggestion not found")
    final_reference = False
    if suggestion.get("image_path"):
        references = lifecycle.path_references(suggestion["image_path"])
        final_reference = len(references) <= 1
    active = db.fetch_one(
        "SELECT id FROM generation_jobs WHERE status IN ('queued','running','switching') "
        "AND json_extract(payload_json,'$.suggestion_id')=? LIMIT 1", (suggestion_id,),
    )
    return {"suggestion_id": suggestion_id, "has_managed_image": bool(suggestion.get("image_path")),
            "final_file_reference": final_reference, "active_job_id": active["id"] if active else None}


@app.post("/api/projects/{project_id}/see", status_code=202)
async def generate_current_scene_image(project_id: str, request: SceneImageRequest) -> dict[str, Any]:
    project = require_project(project_id)
    node_id = request.node_id or project.get("active_node_id")
    path = db.story_path(node_id)
    scene = next((node for node in reversed(path) if node["role"] == "assistant"), None)
    if not scene:
        raise HTTPException(400, "Write or generate a scene before using See")
    preset = db.fetch_one(
        "SELECT id, validation_status FROM workflow_presets WHERE id = ?", (request.workflow_preset_id,)
    )
    if not preset:
        raise HTTPException(404, "Workflow preset not found")
    if preset["validation_status"] == "invalid":
        raise HTTPException(422, "Validate or edit the selected workflow preset before using See")
    await require_comfy_for_image()
    suggestion = db.fetch_one(
        "SELECT * FROM image_suggestions WHERE story_node_id = ? ORDER BY created_at DESC LIMIT 1", (scene["id"],)
    )
    prompt = request.prompt.strip() or scene["content"][-2000:]
    now = utc_now()
    if not suggestion:
        suggestion_id = new_id()
        db.execute(
            "INSERT INTO image_suggestions(id, story_node_id, title, prompt, negative_prompt, status, created_at, updated_at) "
            "VALUES (?, ?, 'Current scene', ?, ?, 'suggested', ?, ?)",
            (suggestion_id, scene["id"], prompt, request.negative_prompt, now, now),
        )
        suggestion = db.fetch_one("SELECT * FROM image_suggestions WHERE id = ?", (suggestion_id,)) or {}
    else:
        db.execute(
            "UPDATE image_suggestions SET prompt = ?, negative_prompt = ?, status = 'suggested', updated_at = ? WHERE id = ?",
            (prompt, request.negative_prompt, now, suggestion["id"]),
        )
    values = request.model_dump(exclude={"workflow_preset_id", "node_id"})
    try:
        values["prompt"], references = expand_image_prompt(db, scheduler.world, project_id, scene["id"], prompt)
    except ImagePromptReferenceError as exc:
        raise HTTPException(422, str(exc)) from exc
    actor = current_user()
    job = db.create_job(project_id, "image", {
        "suggestion_id": suggestion["id"], "preset_id": request.workflow_preset_id, "values": values,
        "template_prompt": prompt, "prompt_references": references,
    }, actor.id, actor.username)
    db.execute("UPDATE image_suggestions SET status = 'queued', updated_at = ? WHERE id = ?", (utc_now(), suggestion["id"]))
    await scheduler.enqueue(job["id"])
    return {"job": job, "suggestion_id": suggestion["id"], "story_node_id": scene["id"]}


@app.post("/api/suggestions/{suggestion_id}/generate", status_code=202)
async def generate_image(suggestion_id: str, request: ImageGenerateRequest) -> dict[str, Any]:
    suggestion = db.fetch_one(
        "SELECT s.*, n.project_id FROM image_suggestions s JOIN story_nodes n ON n.id = s.story_node_id "
        "WHERE s.id = ?",
        (suggestion_id,),
    )
    if not suggestion:
        raise HTTPException(404, "Illustration suggestion not found")
    preset = db.fetch_one(
        "SELECT id, validation_status FROM workflow_presets WHERE id = ?", (request.workflow_preset_id,)
    )
    if not preset:
        raise HTTPException(404, "Workflow preset not found")
    if preset["validation_status"] == "invalid":
        raise HTTPException(409, "Workflow preset is invalid; fix its mappings before generating")
    await require_comfy_for_image()
    values = request.model_dump(exclude={"workflow_preset_id"})
    try:
        template_prompt = values["prompt"]
        values["prompt"], references = expand_image_prompt(
            db, scheduler.world, suggestion["project_id"], suggestion["story_node_id"], template_prompt,
        )
    except ImagePromptReferenceError as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = {"suggestion_id": suggestion_id, "preset_id": request.workflow_preset_id, "values": values,
               "template_prompt": template_prompt, "prompt_references": references}
    actor = current_user()
    job = db.create_job(suggestion["project_id"], "image", payload, actor.id, actor.username)
    db.execute(
        "UPDATE image_suggestions SET status = 'queued', updated_at = ? WHERE id = ?",
        (utc_now(), suggestion_id),
    )
    await scheduler.enqueue(job["id"])
    return job


@app.get("/api/workflows")
async def list_workflows() -> list[dict[str, Any]]:
    return data.workflows.list(admin=current_user().admin)


@app.get("/api/workflows/metadata")
async def workflow_metadata() -> dict[str, Any]:
    comfy = ComfyClient(read_settings(db)["comfy_url"])
    if not await comfy.health():
        raise HTTPException(503, "ComfyUI is not running; start it to inspect workflow inputs")
    return await comfy.object_info()


@app.post("/api/workflows", status_code=201)
async def create_workflow(request: WorkflowPresetCreate) -> dict[str, Any]:
    settings = read_settings(db)
    comfy = ComfyClient(settings["comfy_url"])
    object_info = await comfy.object_info() if await comfy.health() else None
    try:
        graph, source_format = normalize_workflow_graph(request.graph, object_info)
    except WorkflowValidationError as exc:
        raise HTTPException(422, {"message": "Invalid workflow file", "errors": [str(exc)]}) from exc
    graph = prune_workflow_graph(graph, request.mappings)
    errors = validate_workflow(graph, request.mappings, object_info)
    if errors:
        raise HTTPException(422, {"message": "Invalid workflow mapping", "errors": errors})
    status, validation_error = "unvalidated", None
    if object_info is not None:
        errors = validate_workflow(graph, request.mappings, object_info)
        status = "invalid" if errors else "valid"
        validation_error = "; ".join(errors) if errors else None
    workflow_id, now = new_id(), utc_now()
    db.execute(
        "INSERT INTO workflow_presets"
        "(id, name, graph_json, mappings_json, validation_status, validation_error, source_graph_json, source_format, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            workflow_id,
            request.name.strip(),
            json.dumps(graph),
            request.mappings.model_dump_json(),
            status,
            validation_error,
            json.dumps(request.graph),
            source_format,
            now,
            now,
        ),
    )
    row = db.fetch_one("SELECT * FROM workflow_presets WHERE id = ?", (workflow_id,))
    result = decode_json_fields(row, "graph_json", "mappings_json") or {}
    result.pop("source_graph_json", None)
    return result


@app.put("/api/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowPresetCreate) -> dict[str, Any]:
    if not db.fetch_one("SELECT id FROM workflow_presets WHERE id = ?", (workflow_id,)):
        raise HTTPException(404, "Workflow preset not found")
    settings = read_settings(db)
    comfy = ComfyClient(settings["comfy_url"])
    object_info = await comfy.object_info() if await comfy.health() else None
    try:
        graph, source_format = normalize_workflow_graph(request.graph, object_info)
    except WorkflowValidationError as exc:
        raise HTTPException(422, {"message": "Invalid workflow file", "errors": [str(exc)]}) from exc
    graph = prune_workflow_graph(graph, request.mappings)
    errors = validate_workflow(graph, request.mappings, object_info)
    if errors:
        raise HTTPException(422, {"message": "Invalid workflow mapping", "errors": errors})
    status = "valid" if object_info is not None else "unvalidated"
    now = utc_now()
    db.execute(
        "UPDATE workflow_presets SET name = ?, graph_json = ?, mappings_json = ?, validation_status = ?, "
        "validation_error = NULL, source_graph_json = ?, source_format = ?, updated_at = ? WHERE id = ?",
        (request.name.strip(), json.dumps(graph), request.mappings.model_dump_json(), status,
         json.dumps(request.graph), source_format, now, workflow_id),
    )
    row = db.fetch_one("SELECT * FROM workflow_presets WHERE id = ?", (workflow_id,))
    return decode_json_fields(row, "graph_json", "mappings_json", "source_graph_json") or {}


@app.post("/api/workflows/{workflow_id}/validate")
async def validate_saved_workflow(workflow_id: str) -> dict[str, Any]:
    row = db.fetch_one("SELECT * FROM workflow_presets WHERE id = ?", (workflow_id,))
    if not row:
        raise HTTPException(404, "Workflow preset not found")
    comfy = ComfyClient(read_settings(db)["comfy_url"])
    if not await comfy.health():
        raise HTTPException(503, "ComfyUI is not running; start runtimes before validation")
    mappings = json.loads(row["mappings_json"])
    errors = validate_workflow(
        json.loads(row["graph_json"]),
        WorkflowMappings.model_validate(mappings),
        await comfy.object_info(),
    )
    status = "invalid" if errors else "valid"
    db.execute(
        "UPDATE workflow_presets SET validation_status = ?, validation_error = ?, updated_at = ? WHERE id = ?",
        (status, "; ".join(errors) if errors else None, utc_now(), workflow_id),
    )
    return {"status": status, "errors": errors}


@app.delete("/api/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str) -> None:
    if not data.workflows.exists(workflow_id):
        raise HTTPException(404, "Workflow preset not found")
    active = data.workflows.active_job(workflow_id)
    if active:
        raise HTTPException(409, {"message": "Workflow is used by an active image job", "recovery_actions": ["cancel_job", "retry_after_completion"]})
    data.workflows.delete(workflow_id)


@app.get("/api/workflows/{workflow_id}/delete-impact")
async def workflow_delete_impact(workflow_id: str) -> dict[str, Any]:
    workflow = data.workflows.get(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow preset not found")
    return {"workflow_id": workflow_id, "name": workflow["name"], "confirmation": workflow["name"], "counts": {"historical_jobs": data.workflows.historical_job_count(workflow_id)}}


@app.get("/api/jobs")
async def list_jobs(project_id: str | None = None) -> list[dict[str, Any]]:
    user = current_user()
    assigned = [] if user.admin else data.projects.assigned_project_ids(user.id)
    try:
        return route_data.list_jobs(admin=user.admin, assigned_project_ids=assigned, requested_project_id=project_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = route_data.get_job(job_id, admin=current_user().admin)
    if not job:
        raise HTTPException(404, "Generation job not found")
    return job


def _member_job_view(job: dict[str, Any]) -> dict[str, Any]:
    permitted = {
        "id", "project_id", "kind", "status", "phase", "progress_current", "progress_total",
        "progress_message", "error", "created_at", "updated_at", "requested_by_user_id",
        "requester_name_snapshot", "partial_output", "metrics",
    }
    return {key: value for key, value in job.items() if key in permitted}


@app.post("/api/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(job_id: str) -> dict[str, str]:
    if not data.jobs.get(job_id):
        raise HTTPException(404, "Generation job not found")
    await scheduler.cancel(job_id)
    return {"status": "cancellation_requested"}


@app.delete("/api/jobs/history")
async def clear_terminal_job_history(project_id: str | None = None) -> dict[str, int]:
    if project_id:
        require_project(project_id)
    return {"removed": data.jobs.clear_terminal(TERMINAL_JOB_STATUSES, project_id=project_id)}


@app.get("/api/data/summary")
async def data_summary() -> dict[str, Any]:
    return lifecycle.summary()


@app.post("/api/data/garbage-collect")
async def garbage_collect_data() -> dict[str, Any]:
    return lifecycle.garbage_collect()


@app.post("/api/data/delete-story-content")
async def delete_all_story_content(request: DataResetRequest) -> dict[str, Any]:
    if request.confirmation != "DELETE STORY CONTENT":
        raise HTTPException(422, "Type DELETE STORY CONTENT to confirm")
    try:
        return lifecycle.clear_all_story_content()
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc


@app.post("/api/data/factory-reset")
async def factory_reset(request: DataResetRequest) -> dict[str, Any]:
    if request.confirmation != "DELETE ALL LOCAL DATA":
        raise HTTPException(422, "Type DELETE ALL LOCAL DATA to confirm")
    try:
        await supervisor.shutdown()
        scheduler.llama = scheduler.comfy = None
        scheduler.gpu_owner = None
        scheduler.llama_runtime_mode = "normal"
        scheduler.llama_requested_context_tokens = None
        scheduler.transition_reason = "factory reset"
        return lifecycle.factory_reset()
    except LifecycleConflict as exc:
        raise HTTPException(409, {"message": str(exc), "recovery_actions": exc.actions}) from exc


@app.get("/api/runtime")
async def runtime_status() -> dict[str, Any]:
    model_status = await scheduler.llama.model_status() if scheduler.llama and hasattr(scheduler.llama, "model_status") else None
    properties = await scheduler.llama.runtime_properties() if scheduler.llama and hasattr(scheduler.llama, "runtime_properties") else None
    return {
        "state": scheduler.state,
        "current_job_id": scheduler.current_job_id,
        "queued": scheduler.queue.qsize(),
        "log_tail": supervisor.log_tail,
        "gpu_owner": scheduler.gpu_owner,
        "model_status": model_status,
        "transition_reason": scheduler.transition_reason,
        "load_count": scheduler.load_count,
        "unload_count": scheduler.unload_count,
        "effective_context_tokens": (properties or {}).get("effective_context_tokens"),
        "requested_context_tokens": scheduler.llama_requested_context_tokens,
        "runtime_mode": scheduler.llama_runtime_mode,
        "managed_by_storystudio": supervisor.manages_llama,
    }


@app.get("/api/version")
async def build_version() -> dict[str, str]:
    return {"version": BUILD_VERSION}


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return read_settings(db)


@app.put("/api/settings")
async def update_settings(request: RuntimeSettingsUpdate) -> dict[str, Any]:
    if scheduler.current_job_id:
        raise HTTPException(409, "Wait for the active generation job to finish before changing runtimes")
    values = request.model_dump(mode="json")
    await supervisor.shutdown()
    scheduler.llama = scheduler.comfy = None
    scheduler.gpu_owner = None
    scheduler.llama_runtime_mode = "normal"
    scheduler.llama_requested_context_tokens = None
    scheduler.transition_reason = "runtime settings changed"
    requested_data_dir = Path(values["data_dir"]) if values["data_dir"] else db.data_dir
    try:
        db.relocate(requested_data_dir)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    db.execute(
        "UPDATE runtime_settings SET llama_executable = ?, storyteller_model_path = ?, "
        "storyteller_model_id = ?, llama_url = ?, llama_extra_args_json = ?, comfy_command_json = ?, "
        "comfy_workdir = ?, comfy_url = ?, context_tokens = ?, planning_context_tokens = ?, memory_provider = ?, "
        "portrait_prompt_prefix = ?, full_body_prompt_prefix = ?, icon_prompt_prefix = ?, updated_at = ? WHERE id = 1",
        (
            values["llama_executable"],
            values["storyteller_model_path"],
            values["storyteller_model_id"],
            values["llama_url"],
            json.dumps(values["llama_extra_args"]),
            json.dumps(values["comfy_command"]),
            values["comfy_workdir"],
            values["comfy_url"],
            values["context_tokens"],
            values["planning_context_tokens"],
            values["memory_provider"],
            values["portrait_prompt_prefix"],
            values["full_body_prompt_prefix"],
            values["icon_prompt_prefix"],
            utc_now(),
        ),
    )
    return read_settings(db)


@app.post("/api/projects/{project_id}/memory/sync")
async def sync_optional_memory(project_id: str) -> dict[str, Any]:
    require_project(project_id)
    settings = read_settings(db)
    provider = provider_for(settings.get("memory_provider", "builtin"), db, scheduler.world)
    return await provider.index_project(project_id)


@app.post("/api/settings/validate")
async def validate_settings(request: RuntimeSettingsUpdate) -> dict[str, Any]:
    values = request.model_dump(mode="json")
    issues: list[str] = []
    requested_data_dir = Path(values["data_dir"]) if values["data_dir"] else db.data_dir
    if requested_data_dir.exists() and not requested_data_dir.is_dir():
        issues.append("Application data path is not a directory")
    if not Path(values["llama_executable"]).is_file():
        issues.append("llama-server executable does not exist")
    if not Path(values["storyteller_model_path"]).is_file():
        issues.append("Storyteller GGUF model does not exist")
    if not values["comfy_command"]:
        issues.append("ComfyUI launch command is empty")
    if not Path(values["comfy_workdir"]).is_dir():
        issues.append("ComfyUI working directory does not exist")
    cuda_available = await check_cuda()
    if not cuda_available:
        issues.append("NVIDIA CUDA was not detected through nvidia-smi")
    model_id = values["storyteller_model_id"] or Path(values["storyteller_model_path"]).stem
    llama_client = LlamaClient(values["llama_url"], model_id)
    llama_online = await llama_client.health()
    llama_capabilities = await llama_client.planning_capabilities() if llama_online else {
        "apply_template": False, "completion": False, "props": False, "effective_context_tokens": None,
    }
    if llama_online:
        missing = [name for name in ("apply_template", "completion", "props") if not llama_capabilities.get(name)]
        if missing:
            issues.append("llama.cpp must be updated for planning autocomplete; missing endpoints: " + ", ".join(missing))
        effective = llama_capabilities.get("effective_context_tokens")
        if effective and not supervisor.manages_llama and int(effective) < values["planning_context_tokens"]:
            issues.append(
                f"External llama.cpp provides {int(effective):,} context tokens, but planning requests {values['planning_context_tokens']:,}"
            )
    comfy_online = await ComfyClient(values["comfy_url"]).health()
    return {
        "valid": not issues,
        "issues": issues,
        "cuda_available": cuda_available,
        "llama_online": llama_online,
        "comfy_online": comfy_online,
        "llama_capabilities": llama_capabilities,
    }


async def check_cuda() -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=name",
            "--format=csv,noheader",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        return process.returncode == 0 and bool(stdout.strip())
    except (FileNotFoundError, TimeoutError):
        return False


@app.post("/api/runtime/start")
async def start_runtimes() -> dict[str, str]:
    if not await check_cuda():
        raise HTTPException(503, "NVIDIA CUDA was not detected through nvidia-smi")
    await scheduler._set_state("loading_storyteller")
    try:
        llama, comfy = await scheduler._ensure_runtimes()
        await comfy.free()
        await llama.load()
        scheduler.gpu_owner = "storyteller"
    except Exception as exc:
        await scheduler._set_state("runtime_error", detail=str(exc))
        raise HTTPException(503, str(exc)) from exc
    await scheduler._set_state("idle")
    return {"status": "ready"}


@app.get("/media/{relative_path:path}")
async def media(relative_path: str) -> FileResponse:
    requested = (db.data_dir / relative_path).resolve()
    root = db.data_dir.resolve()
    normalized = relative_path.replace("\\", "/")
    if root not in requested.parents or not requested.is_file() or not normalized.startswith(("images/", "music/")):
        raise HTTPException(404, "Media not found")
    return FileResponse(requested)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
sound_dir = Path(__file__).resolve().parents[2] / "public" / "sounds"
if sound_dir.is_dir():
    app.mount("/sounds", StaticFiles(directory=sound_dir), name="sounds")
if frontend_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        candidate = (frontend_dist / path).resolve()
        if frontend_dist.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
