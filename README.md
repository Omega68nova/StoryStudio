# StoryStudio

StoryStudio is a local-first storytelling workspace that coordinates a GGUF storyteller through `llama-server` and arbitrary ComfyUI API workflows. It keeps one GPU-heavy workload resident at a time and uses an event-sourced, branch-aware world model so characters, geography, knowledge, chronology, and image references remain correct at historical story heads.

## Authenticated multiplayer

StoryStudio uses administrator-created accounts, Argon2id password hashes, seven-day HTTP-only sessions, assignment-filtered stories/media/jobs, and same-origin authenticated WebSockets. Administrators retain the complete editor. Members receive only assigned stories, the story composer, editable Story Bible, illustration generation, minigame resolution, and their local music player; unclassified member API routes are denied by default.

Before the first start, create the bootstrap administrator interactively. The password is read without echo and is never written to source or configuration:

```powershell
.\bootstrap-admin.ps1
```

The Users workspace creates accounts, resets passwords, disables accounts, and assigns stories. Password changes and administrative resets revoke existing sessions. Queued player actions are persisted in FIFO order and attach to the latest shared story head only when generation starts, avoiding malformed branches from simultaneous phones. Music theme and current-track selections are synchronized and announced to assigned listeners; play/pause, position, and volume remain local to each browser.

## Temporal world memory

- SQLite is the sole source of truth. Typed world changes are immutable transactions committed atomically with storyteller prose.
- Selecting a branch head replays only its ancestry; undo moves the head and removes that turn's prose, movement, knowledge, time, and other changes together without deleting alternate futures.
- Characters keep persistent personality, appearance, wardrobe, equipment, abilities, position, relationships, knowledge, and player-control state. Every change creates a historical lore-card version used by scene-era image prompts.
- Locations have hierarchical coordinates and explicit route edges. Cardinal/nearby queries are derived from coordinates, while movement requires a traversable route or a validated ability bypass.
- Scene perspective filters facts for first-person and third-person-limited narration. Omniscient narration receives narrator scope.
- Story generation uses bounded read tools for discovery and staged write tools for proposed changes. Major or irreversible changes require approval; routine validated changes commit automatically.

The optional six-stage Preplanning workspace covers foundation, lore systems, major and secondary locations, routes, cast/factions, and flexible plot beats. Each generated JSON draft is editable and must be explicitly approved before becoming canonical root-world events. Existing story-bible text is preserved unchanged and has a separate explicit import action in the World workspace.

## NPCs, media, music, and rules

- Autonomous NPCs can be enabled per character at low, normal, or high frequency. Up to three present NPCs are selected deterministically for one batched model pass; their cited knowledge, actor identity, targets, and ability costs are validated before their attempts reach the storyteller.
- Character outfits have stable IDs and can carry a featured portrait and full-body image. Locations can carry a featured scene image. First encounters retain the story-head outfit reference, and image prompts are built from that historical lore-card version. PNG, JPEG, and WebP uploads are copied into guarded managed storage.
- The Music workspace manages shared local MP3, OGG, WAV, and M4A playlists. Each theme supports shuffle, loop-one, or ordered playback; a compact player persists across workspaces with explicit pause and stop controls. Projects explicitly allow themes and choose disabled, player-managed, or AI-managed playback. AI cues are branch events.
- Optional project rules define bounded character or relationship stats and simple abilities with costs, immediate effects, and turn- or story-minute-based temporary effects. New stories may start empty or use adventure and romance presets. Values and effects are event-sourced, so undoing or changing branches restores them with the story.

Uploaded files are checked by content signature rather than filename alone. StoryStudio does not transcode audio or automatically install models, custom nodes, or workflows.

## Environment and ambient sound

The Environment workspace configures branch-aware scene focus, physical `-ing` actions, directed weather transitions, a customizable repeating time-of-day cycle, nested locations, discovery-filtered maps, and conditional location backgrounds. The storyteller receives only the active scene and uses bounded location/map/route tools when it needs distant geography; ambient rules, sound paths, background libraries, and the complete map are never placed in its initial context.

Ambient sound is independent from Music. Administrators assign recursively indexed loops from `public/sounds` to weather, time phases, locations, location tags, and actions, and may define a sped-up or slowed-down file as a separate sound variant. Each signed-in user has only an ambient enable switch and master volume. Matching loops mix additively and crossfade after the browser's first interaction; isolated locations suppress external weather/time layers. Production serves the read-only library at `/sounds/`, while uploaded/generated backgrounds continue to use guarded `/media/` storage.

## Resumable minigames

The Minigames workspace configures eleven bundled, versioned challenges: d20, d6, coin flip, timing, key spam, fishing/red light, lockpicking, a seven-tile hex circuit, circled teeth, timed attack, and a five-second dodge box. Every game starts disabled. Eligibility is filtered from project rules, action direction, entity tags, location tags, and difficulty; composer actions influence recommendations without hiding an enabled game. Puzzle games support persisted server-generated setups; attack abilities may define timing profiles, while physical lockpicks come from branch-aware structured character inventory.

Games are browsable and batch-toggleable as Chance, Cypher, Reflex, Strength / Effort, Fishing, Attack, and Take Attack groups. Enabled games may be invoked during any storyteller response; composer action preferences and deterministic wording matches rank recommendations without preventing situational challenges such as an enemy attack during Continue. The story configuration popover also provides persistent project-authored storyteller context for behavioral and minigame preferences.

The Bullet Hell workspace supplies shared, cloneable attack, mode, and skill catalogs. Projects explicitly allow definitions; characters may select a default mode, own skills directly or through abilities, and enemies may force one mode on compatible attacks. Dodge checkpoints snapshot seeded Particle Rain, telegraphed Third-Screen Beam, or eight-direction Spear Volley hazards; Base, Blue gravity, or centered Green shield movement; optional collision-immune rolling; and the authoritative five-second server replay.

An inline challenge saves a durable checkpoint instead of committing an incomplete turn. A turn may contain several sequential challenges, while only one may await player input at a time. The scheduler is released while the player responds and llama.cpp remains resident. Chance results are generated by the backend; timing and key-spam results are submitted by the local browser. The same story operation then resumes from its saved prose and commits the final prose, all challenge results, and validated world actions atomically. Refresh and restart recovery preserve unresolved challenges, and cancelling one discards its uncommitted prose and actions.

## Recovery and data lifecycle

The Data workspace reports record counts, managed disk usage, active work, recoverable trash, orphaned media, and dangling search rows. StoryStudio reference-counts shared audio and image paths before removing files and records failed filesystem cleanup for a safe retry. Per-object archive/trash remains the default; permanent story, entity, planning, and project removal requires an impact review and typed confirmation. “Delete all story content” preserves runtime settings and shared libraries, while factory reset removes all StoryStudio-owned local data without touching llama.cpp, GGUF, ComfyUI, checkpoints, or custom nodes.

Planning stages use one guarded state machine and revision ownership. On startup, legacy drafts and abandoned generation are repaired, approved JSON remains authoritative, late results remain in revision history, and the current stage is recomputed. Approval checks the current world for collisions and supports link, merge, rename, or omit before committing a unique revision hash.

## Requirements

- Windows 10/11 with an NVIDIA GPU
- Python 3.11 or newer
- Node.js 20 or newer
- A recent `llama-server` build with router-mode `/models/load` and `/models/unload`
- A working ComfyUI installation
- A compatible GGUF storyteller model and the checkpoints referenced by imported ComfyUI workflows

## Development

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Configure the inference runtimes in Settings before generating content. By default, persistent data lives in `%LOCALAPPDATA%\StoryStudio`; override it with `STORYSTUDIO_DATA_DIR`.

Built-in retrieval uses SQLite full-text search plus deterministic graph traversal. To enable Cognee as an optional CPU-side candidate index:

```powershell
cd backend
.venv\Scripts\python -m pip install -r requirements-memory.txt
```

Then select Cognee in Settings. StoryStudio lazily imports it, uses local storage and CPU embeddings, accepts only candidate entity IDs from it, and rechecks branch membership, visibility, and canonical values. An unavailable or failed adapter falls back to built-in retrieval.

For a normal local installation, run `setup.ps1` once and then launch the complete built application with `start.ps1`. It is served at `http://127.0.0.1:8765`.

For public phone access, keep that loopback binding and follow [deploy/README.md](deploy/README.md). Caddy alone listens on HTTPS 443. Do not expose Uvicorn, llama.cpp, ComfyUI, or public port 8765 directly.

## Runtime contract

StoryStudio starts only the processes it owns. It launches `llama-server` in router mode using the configured executable and the GGUF model's parent directory. The configured ComfyUI command is passed as an argument array, never through a shell. All services bind to loopback.

ComfyUI imports accept API prompt JSON directly. Editable UI workflow JSON is converted using the running ComfyUI node metadata, including subgraph expansion and pruning to the selected output; the untouched source graph is retained alongside the executable copy. Each preset maps app fields to concrete node IDs and input names. StoryStudio never installs custom nodes or models.

The storyteller pipeline supports Direct, Low, and Smart planning modes, then streams prose with hidden validated inline world actions. NPC attempts, illustration ideas, and eligible minigame checkpoints share that bounded protocol. Ordinary turns keep llama.cpp resident; only a validated image job unloads it. It does not inject the complete world database into prompts.

## Verification

```powershell
cd backend
.venv\Scripts\python -m pytest
cd ..\frontend
npm run test
npm run build
npm run test:e2e
```
