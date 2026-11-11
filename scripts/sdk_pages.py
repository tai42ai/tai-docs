"""The catalogue of Python SDK reference pages.

Declares what the reference documents: ``PAGES`` lists each page (its slug,
title, description, icon, and the modules it renders), and ``REQUIRED_SYMBOLS``
lists the public names that must appear as a rendered heading. ``gen_sdk``
renders from this catalogue; nothing here touches griffe or the filesystem.
"""

from __future__ import annotations

# Each page renders one or more modules. Order is stable so the generated nav
# and anchors do not churn between runs.
PAGES: list[dict] = [
    {
        "slug": "contract-app",
        "title": "App facade (tai42_contract.app)",
        "description": "The assembled TaiApp facade and its per-feature namespaces.",
        "icon": "layer-group",
        "modules": ["tai42_contract.app", "tai42_contract.app.facets"],
    },
    {
        "slug": "contract-agent",
        "title": "Agents (tai42_contract.agent)",
        "description": "The Agent base class plugin authors subclass.",
        "icon": "robot",
        "modules": ["tai42_contract.agent"],
    },
    {
        "slug": "contract-versioning",
        "title": "Versioning (tai42_contract.versioning)",
        "description": "The VersionedStore primitive behind presets and policies.",
        "icon": "code-branch",
        "modules": ["tai42_contract.versioning"],
    },
    {
        "slug": "contract-presets",
        "title": "Presets (tai42_contract.presets)",
        "description": "The PresetStore protocol and preset document models.",
        "icon": "sliders",
        "modules": ["tai42_contract.presets"],
    },
    {
        "slug": "contract-connectors",
        "title": "Connectors (tai42_contract.connectors)",
        "description": "The ProviderDescriptor a connector plugin declares.",
        "icon": "plug",
        "modules": ["tai42_contract.connectors.providers"],
    },
    {
        "slug": "contract-extensions",
        "title": "Extensions (tai42_contract.extensions)",
        "description": "The ExtensionKind taxonomy and extension base surface.",
        "icon": "puzzle-piece",
        "modules": ["tai42_contract.extensions"],
    },
    {
        "slug": "contract-monitoring",
        "title": "Monitoring (tai42_contract.monitoring)",
        "description": "The MonitoringReader and MonitoringWriter protocols.",
        "icon": "chart-line",
        "modules": ["tai42_contract.monitoring.reader", "tai42_contract.monitoring.writer"],
    },
    {
        "slug": "contract-storage",
        "title": "Storage (tai42_contract.storage)",
        "description": "The Storage protocol a storage provider implements.",
        "icon": "database",
        "modules": ["tai42_contract.storage"],
    },
    {
        "slug": "contract-backend",
        "title": "Backends (tai42_contract.backend)",
        "description": (
            "The Backend protocol a compute backend implements, and the seams the kit builds every backend's "
            "tools over: the TaskDoor its task branches queue through, the ScheduleWriter and ScheduleStore "
            "its schedules are written and read through, and the WorkerInspection its task and worker views read."
        ),
        "icon": "server",
        "modules": ["tai42_contract.backend"],
    },
    {
        "slug": "contract-sandbox",
        "title": "Sandbox (tai42_contract.sandbox)",
        "description": "The Sandbox ABC a sandbox provider implements, plus its session, spec, and policy models.",
        "icon": "box",
        "modules": ["tai42_contract.sandbox"],
    },
    {
        "slug": "contract-channels",
        "title": "Channels (tai42_contract.channels)",
        "description": "The Channel protocol a delivery channel plugin implements.",
        "icon": "paper-plane",
        "modules": ["tai42_contract.channels"],
    },
    {
        "slug": "contract-accounts",
        "title": "Accounts (tai42_contract.accounts)",
        "description": "The AccountsProvider contract and the login-method metadata models.",
        "icon": "user-lock",
        "modules": [
            "tai42_contract.accounts.provider",
            "tai42_contract.accounts.models",
        ],
    },
    {
        "slug": "contract-tools",
        "title": "Tools (tai42_contract.tools)",
        "description": "Tool registration types and the app tools namespace.",
        "icon": "wrench",
        "modules": ["tai42_contract.tools"],
    },
    {
        "slug": "contract-manifest",
        "title": "Manifest (tai42_contract.manifest)",
        "description": "The manifest model a server loads at startup.",
        "icon": "file-lines",
        "modules": ["tai42_contract.manifest"],
    },
    {
        "slug": "contract-plugins",
        "title": "Plugins (tai42_contract.plugins)",
        "description": "The PluginSpec model behind tai-plugin.yml.",
        "icon": "store",
        "modules": ["tai42_contract.plugins"],
    },
    {
        "slug": "contract-interactions",
        "title": "Interaction outcomes (tai42_contract.interactions)",
        "description": "The typed outcomes a resumed run returns: suspended, buffered, and failed.",
        "icon": "comments",
        "modules": ["tai42_contract.interactions.models.response"],
    },
    {
        "slug": "kit-plugins",
        "title": "Plugin I/O and env (tai42_kit.plugins)",
        "description": "Loading a tai-plugin.yml, reading its docs, and deriving the env a spec requires.",
        "icon": "store",
        "modules": ["tai42_kit.plugins"],
    },
    {
        "slug": "kit-registration",
        "title": "Provider registration (tai42_kit.access_control, tai42_kit.accounts)",
        "description": "The identity-provider and accounts-provider registries a plugin registers into at import.",
        "icon": "id-card",
        "modules": ["tai42_kit.access_control.registry", "tai42_kit.accounts.registry"],
    },
    {
        "slug": "kit-clients",
        "title": "Pooled clients (tai42_kit.clients)",
        "description": "Pooled Postgres/Redis clients and connection settings.",
        "icon": "network-wired",
        "modules": ["tai42_kit.clients"],
    },
    {
        "slug": "kit-postgres",
        "title": "Postgres client (tai42_kit.clients.impl.postgres)",
        "description": "The pooled Postgres client, autocommit reads, pinned and dedicated connections.",
        "icon": "database",
        "modules": ["tai42_kit.clients.impl.postgres"],
    },
    {
        "slug": "kit-loop-bound",
        "title": "Loop-bound resources (tai42_kit.loop_bound)",
        "description": (
            "The per-event-loop, per-client-epoch resource registries, the close of a retired epoch's "
            "registries, and the one release of a loop's registries and then its pooled clients, run at "
            "the loop's end or at an app's shutdown on a loop that lives on."
        ),
        "icon": "arrows-rotate",
        "modules": ["tai42_kit.loop_bound"],
    },
    {
        "slug": "kit-private-loop",
        "title": "Private event loop (tai42_kit.backend.private_loop)",
        "description": (
            "The event loop a backend job's OS thread runs itself, and the end that loop runs: the loop "
            "marked closing, its loop-bound resources released, its leftover tasks cancelled and ended, "
            "its async generators closed."
        ),
        "icon": "rotate",
        "modules": ["tai42_kit.backend.private_loop"],
    },
    {
        "slug": "kit-shared-loop",
        "title": "Shared event loop (tai42_kit.backend.shared_loop)",
        "description": (
            "The host's running event loop, shared with the jobs of a backend pool that runs them "
            "as green threads of the host's OS thread."
        ),
        "icon": "share-nodes",
        "modules": ["tai42_kit.backend.shared_loop"],
    },
    {
        "slug": "kit-loop-closing",
        "title": "Closing event loops (tai42_kit.loop_closing)",
        "description": (
            "The mark a loop's end sets before it releases the loop's resources, and the refusal every "
            "loop-bound owner raises on a new lease against a closing loop."
        ),
        "icon": "circle-stop",
        "modules": ["tai42_kit.loop_closing"],
    },
    {
        "slug": "kit-compute",
        "title": "Compute pool (tai42_kit.compute)",
        "description": (
            "The pool of worker processes a process runs its CPU-bound jobs in, off the event loop: the pool, "
            "its share with the children a process forks, the pool host a process started through a prelude "
            "runs its jobs in, the client that reaches a pool over a socket, the COMPUTE_WORKERS setting that "
            "sizes it, and the errors a job raises."
        ),
        "icon": "gears",
        "modules": ["tai42_kit.compute"],
    },
    {
        "slug": "kit-backend-tools",
        "title": "Backend tools (tai42_kit.backend tool surface)",
        "description": (
            "The backend_* tool surface every backend offers, built once by the kit: the ten schedule tools "
            "over a ScheduleStore, the twelve task and worker tools over a WorkerInspection, and the "
            "UnsupportedBackendTool refusal."
        ),
        "icon": "toolbox",
        "modules": [
            "tai42_kit.backend.tool_surface",
            "tai42_kit.backend.schedule_tools",
            "tai42_kit.backend.inspection_tools",
        ],
    },
    {
        "slug": "kit-backend-dispatch",
        "title": "Backend dispatch (tai42_kit.backend dispatch helpers)",
        "description": (
            "The sync, async, and schedule branch tools every backend registers over its TaskDoor and "
            "ScheduleWriter, their task options, the worker queue labels, and the checks every schedule write shares."
        ),
        "icon": "shuffle",
        "modules": [
            "tai42_kit.backend.branches",
            "tai42_kit.backend.task_options",
            "tai42_kit.backend.queue_labels",
            "tai42_kit.backend.schedule_writes",
        ],
    },
    {
        "slug": "kit-llm",
        "title": "LLM factories and the classifier contract (tai42_kit.llm)",
        "description": "LLM, embedding, checkpoint, and store factories, plus the classifier contract models.",
        "icon": "brain",
        "modules": ["tai42_kit.llm", "tai42_kit.llm.classifier"],
    },
    {
        "slug": "kit-monitoring",
        "title": "Run traces (tai42_kit.monitoring)",
        "description": (
            "The run-trace opener: a run's one lineage, its `run` span, "
            "and the span that continues a handed-over lineage."
        ),
        "icon": "diagram-project",
        "modules": ["tai42_kit.monitoring.run_trace"],
    },
    {
        "slug": "kit-checkpoint",
        "title": "Checkpoint stores (tai42_kit.llm.checkpoint)",
        "description": (
            "The checkpoint-store seam: the provider registry and its facts, the resource and retention seams, "
            "and the protocols and helpers a store's registration builds on."
        ),
        "icon": "floppy-disk",
        "modules": ["tai42_kit.llm.checkpoint"],
    },
    {
        "slug": "kit-settings",
        "title": "Settings (tai42_kit.settings)",
        "description": "The base settings class and the settings registry.",
        "icon": "gear",
        "modules": ["tai42_kit.settings"],
    },
    {
        "slug": "kit-transport",
        "title": "Transports (tai42_kit.transport)",
        "description": "UDS transports and the MCP transport factory.",
        "icon": "route",
        "modules": ["tai42_kit.transport"],
    },
    {
        "slug": "kit-net",
        "title": "Network guard (tai42_kit.net)",
        "description": "The URL guard and safe fetch helpers.",
        "icon": "shield-halved",
        "modules": ["tai42_kit.net"],
    },
    {
        "slug": "kit-interactions",
        "title": "Park index and park seams (tai42_kit.interactions)",
        "description": (
            "The shared park index, the terminal chain notice, and the give-up handler seam a driver "
            "that parks registers so the waiter of a park its driver ends (an abandoned resume, or a "
            "resumed answer a preset's output map refused) is told."
        ),
        "icon": "square-parking",
        "modules": [
            "tai42_kit.interactions.park_index",
            "tai42_kit.interactions.park_adoption",
            "tai42_kit.interactions.park_giveup",
        ],
    },
    {
        "slug": "kit-logging",
        "title": "Logging (tai42_kit.logging)",
        "description": "Structured logging settings and setup.",
        "icon": "file-lines",
        "modules": ["tai42_kit.logging"],
    },
    {
        "slug": "skeleton-app",
        "title": "Skeleton app (tai42_skeleton.app)",
        "description": "The concrete TaiMCP app, including the raw fastmcp escape hatch.",
        "icon": "microchip",
        "modules": ["tai42_skeleton.app.server"],
    },
    {
        "slug": "skeleton-asgi",
        "title": "ASGI factory (tai42_skeleton.asgi)",
        "description": "The public create_app factory for embedding the server in a user-owned ASGI process.",
        "icon": "server",
        "modules": ["tai42_skeleton.asgi"],
    },
    {
        "slug": "skeleton-states",
        "title": "State record validation (tai42_skeleton.states)",
        "description": (
            "The store-free record validator, the effective-schema composer, and the state-template document validator."
        ),
        "icon": "list-check",
        "modules": [
            "tai42_skeleton.states.schema",
            "tai42_skeleton.states.templates.compose",
            "tai42_skeleton.states.templates.validate",
        ],
    },
]

# The public Protocols/ABCs a plugin author implements, the backend seams and
# the kit registrars that build the backend tools over them, the escape-hatch
# accessor, the guarded fetch helper, the Postgres client's connection
# helpers, and the store-free record validator. Every one MUST appear as a
# rendered heading or the run fails.
REQUIRED_SYMBOLS = [
    "Agent",
    "VersionedStore",
    "AppVersioning",
    "AppPresets",
    "PresetStore",
    "MonitoringReader",
    "MonitoringWriter",
    "ProviderDescriptor",
    "ExtensionKind",
    "TaiApp",
    "Backend",
    "TaskDoor",
    "ScheduleWriter",
    "ScheduleStore",
    "WorkerInspection",
    "BackendInspection",
    "UnsupportedBackendTool",
    "register_schedule_tools",
    "register_inspection_tools",
    "register_task_branches",
    "Sandbox",
    "Storage",
    "Channel",
    "PluginSpec",
    "fastmcp",
    "fetch_url",
    "RunFailed",
    "ParkIndex",
    "terminal_chain_notice",
    "ParkGiveUpOutcome",
    "register_park_giveup_handler",
    "fire_park_giveup",
    "CheckpointProvider",
    "CheckpointValueStore",
    "FinishedThreadLedger",
    "ValueEncoding",
    "PostgresClient",
    "read_connection",
    "pinned_connection",
    "RecordValidator",
]
