"""Live app fixtures the executable-example harness boots before running examples.

An operator ``curl`` example cannot be verified as prose — it must hit a running
app and produce a real status code. Rather than invent a new deployment, these
fixtures reuse the skeleton's OWN access-control test doubles (``FakeRedis`` +
``FakeAccessControlPg`` from ``tests/access_control/conftest.py``) wired into the
REAL access-control middleware chain, then serve that app over a real localhost
socket with uvicorn. The 200 / 403 / 401 an example observes comes from the real
``AuthAdapter`` → ``AccessControlAuthBackend`` → ``ResourceGuardMiddleware`` code
path; only the Redis/Postgres storage seams are faked, exactly as the skeleton's
own end-to-end auth test (``tests/access_control/test_mcp_auth_e2e.py``) does.

Each fixture is a context manager yielding a dict of environment variables that
its examples reference (``$TAI_BASE_URL``, ``$TAI_API_KEY``, …). The harness
merges those into the example's environment. Booting is real but light: no
Postgres, no Redis, no external services — so it runs in the same offline CI job
as the rest of the docs gate.

This module imports the skeleton's private ``tests`` package. That coupling is
deliberate (reuse the real doubles, never re-fake them) and loud: if the skeleton
moves those fakes, importing this module fails immediately instead of silently
drifting.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn
    from tai42_contract.access_control.identity import IdentityProvider
    from tests.access_control.conftest import FakeAccessControlPg, FakeRedis

# The fakes live in the skeleton's test tree. The docs scripts run from the
# skeleton member (cwd = tai42/core/skeleton), but resolve the skeleton root
# explicitly so ``import tests…`` works regardless of the invoking cwd.
_SKELETON_ROOT = Path(__file__).resolve().parent.parent.parent / "tai42" / "core" / "skeleton"
if _SKELETON_ROOT.is_dir() and str(_SKELETON_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKELETON_ROOT))


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# The access-control policy store resolves its Postgres through the central database
# registry, which RAISES when the default database is unconfigured. These fixtures fake
# the transport but model a CONFIGURED deployment (there is no store-less access-control
# serving path), so each snapshots and sets a non-empty default-database password exactly
# as the skeleton's own offline access-control tests do; the value never reaches a socket.
_DEFAULT_DATABASE_PASSWORD_ENV = "TAI_DATABASE_DEFAULT_PG_PASSWORD"  # noqa: S105 - env-var name, not a secret
_DEFAULT_DATABASE_PASSWORD = "docs-example"  # noqa: S105 - offline fixture placeholder, never reaches a socket


def _restore_env(key: str, saved: str | None) -> None:
    if saved is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = saved


def _snapshot_identity_registry() -> dict[str, Callable[..., IdentityProvider]]:
    """Copy the identity-provider registry's current names and factories through its public accessors."""
    from tai42_kit.access_control import registry

    return {
        name: registry.get_identity_provider_factory_staged(name)
        for name in registry.iter_identity_provider_names_staged()
    }


def _restore_identity_registry(saved: dict[str, Callable[..., IdentityProvider]]) -> None:
    """Reinstate exactly the identity providers a :func:`_snapshot_identity_registry` copy holds."""
    from tai42_kit.access_control import registry

    registry.reset_registry()
    for name, factory in saved.items():
        registry.register_identity_provider(name, factory)


def _register_default_identity_provider() -> None:
    """Register the default "redis" identity provider the way a manifest import would.

    The skeleton ships no concrete provider; a deployment lists one in its
    manifest, so each fixture installs it before serving.
    """
    from tai42_identity_redis.redis_api_key_provider import RedisApiKeyProvider
    from tai42_kit.access_control import registry

    registry.reset_registry()
    registry.register_identity_provider("redis", RedisApiKeyProvider)


def _start_uvicorn(app) -> tuple[uvicorn.Server, threading.Thread, int]:
    """Build a uvicorn server for ``app`` on a free localhost port and start it on a daemon thread.

    Returns the server, its thread, and the port so the caller holds the handles
    BEFORE awaiting startup — a startup timeout can then still stop the server
    from the caller's ``finally``.
    """
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread, port


def _await_started(server: uvicorn.Server, name: str) -> None:
    """Poll until the server reports started.

    Raises after 10s so a boot that never comes up fails loud instead of hanging
    the example run.
    """
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"{name} fixture: uvicorn did not start within 10s")
        time.sleep(0.02)


def _stop_uvicorn(server: uvicorn.Server | None, thread: threading.Thread | None) -> None:
    """Ask the server to exit and join its thread.

    Idempotent over the partial-setup paths: each handle is stopped only if it
    was created.
    """
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout=5)


# Fixed demo credentials + scope for the access-control app. The allowed key's
# policy carries the route's scope (→ 200); the denied key authenticates but its
# policy lacks the scope (→ 403); no key at all is rejected 401.
_ALLOW_KEY = "ac-allow-demo-key"
_DENY_KEY = "ac-deny-demo-key"
_SCOPE = "demo-scope"
_GUARDED_PATH = "/guarded"
# The admin operator that minted both scoped keys. Its full scopes cap nothing, so
# each key's effective authority is exactly its own scope set.
_OPERATOR_ID = "operator"


def _seed_ac_store() -> tuple[FakeRedis, FakeAccessControlPg]:
    """Seed the fake Redis and fake policy store for the guarded-route example.

    Redis gets an allowed and a denied key; the policy store gets the guarded
    route's scope and the two users' policies.
    """
    from tai42_contract.access_control import OWNER_USER_ID_CLAIM
    from tai42_identity_redis.settings import redis_identity_settings
    from tai42_kit.utils.data.string_util import hash_api_key
    from tests.access_control.conftest import (  # type: ignore[import-not-found]
        FakeAccessControlPg,
        FakeRedis,
    )

    key_prefix = redis_identity_settings().key_prefix
    fake_redis = FakeRedis(
        hashes={
            f"{key_prefix}{hash_api_key(_ALLOW_KEY)}": {
                "user_id": "allowed-user",
                "description": "allowed",
                "owner_user_id": _OPERATOR_ID,
            },
            f"{key_prefix}{hash_api_key(_DENY_KEY)}": {
                "user_id": "denied-user",
                "description": "denied",
                "owner_user_id": _OPERATOR_ID,
            },
        },
    )
    fake_pg = FakeAccessControlPg()
    fake_pg.add_route(_GUARDED_PATH, _SCOPE)
    fake_pg.add_principal(_OPERATOR_ID, kind="human", display_name="Operator")
    fake_pg.add_policy(_OPERATOR_ID, scopes=["*"])
    fake_pg.add_policy("allowed-user", scopes=[_SCOPE], policy_data={OWNER_USER_ID_CLAIM: _OPERATOR_ID})
    fake_pg.add_policy("denied-user", scopes=[], policy_data={OWNER_USER_ID_CLAIM: _OPERATOR_ID})
    return fake_redis, fake_pg


def _swap_ac_seams(fake_redis: FakeRedis, fake_pg: FakeAccessControlPg) -> list[tuple[object, str, object]]:
    """Point the access-control ``client_ctx`` seams at the fakes.

    Returns the ``(object, attr, original)`` restore list.
    """
    from tai42_identity_redis import redis_api_key_provider as provider_module
    from tai42_skeleton.access_control import policy as policy_module
    from tai42_skeleton.access_control import store as store_module
    from tests.access_control.conftest import make_client_ctx, make_pg_ctx  # type: ignore[import-not-found]

    redis_ctx = make_client_ctx(fake_redis)
    pg_ctx = make_pg_ctx(fake_pg)
    seams: list[tuple[object, str, object]] = []
    for module in (policy_module, provider_module):
        seams.append((module, "client_ctx", module.client_ctx))
        module.client_ctx = redis_ctx  # type: ignore[attr-defined]
    seams.append((store_module, "client_ctx", store_module.client_ctx))
    store_module.client_ctx = pg_ctx  # type: ignore[attr-defined]
    return seams


@contextmanager
def ac_app() -> Iterator[dict[str, str]]:
    """Boot the real access-control middleware chain over a fake store and serve it on a localhost socket.

    Yields ``TAI_BASE_URL`` + an allowed and a denied api key so a ``curl``
    example can observe a real 200 vs 403.
    """
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from tai42_contract.app import tai42_app
    from tai42_skeleton.access_control.adapter import AuthAdapter
    from tai42_skeleton.access_control.settings import AccessControlSettings
    from tests.access_control.conftest import _FakeApp  # type: ignore[import-not-found]

    # Snapshot the process-global state this fixture mutates BEFORE mutating any of
    # it, so the finally can restore exactly. Reading the snapshot is side-effect
    # free; every mutation (registry, bound app, client_ctx seams) happens inside
    # the try below, so the restore runs on EVERY exit — including the
    # uvicorn-startup-timeout path, which raises from inside the try.
    saved_registry = _snapshot_identity_registry()
    saved_db_password = os.environ.get(_DEFAULT_DATABASE_PASSWORD_ENV)
    seams: list[tuple[object, str, object]] = []
    server = None
    thread = None
    try:
        os.environ[_DEFAULT_DATABASE_PASSWORD_ENV] = _DEFAULT_DATABASE_PASSWORD

        _register_default_identity_provider()

        # The auth backend renders the (empty) policy condition through the bound app.
        tai42_app.bind(_FakeApp())

        settings = AccessControlSettings()
        fake_redis, fake_pg = _seed_ac_store()
        seams = _swap_ac_seams(fake_redis, fake_pg)

        async def _guarded(_request):
            return PlainTextResponse("ok")

        app = Starlette(
            routes=[Route(_GUARDED_PATH, _guarded)],
            middleware=AuthAdapter(settings).get_middleware(),
        )
        # Assign the handles BEFORE awaiting startup so a startup-timeout raise still
        # leaves them in scope for the finally to stop the server.
        server, thread, port = _start_uvicorn(app)
        _await_started(server, "ac_app")

        yield {
            "TAI_BASE_URL": f"http://127.0.0.1:{port}",
            "TAI_API_KEY": _ALLOW_KEY,
            "TAI_DENIED_KEY": _DENY_KEY,
        }
    finally:
        # Restore is idempotent and covers every partial-setup path: stop the
        # server (if it was started), undo whichever seams were swapped, unbind the
        # app, and reinstate the identity registry.
        _stop_uvicorn(server, thread)
        for obj, attr, original in seams:
            setattr(obj, attr, original)
        tai42_app.bind(None)
        _restore_identity_registry(saved_registry)
        _restore_env(_DEFAULT_DATABASE_PASSWORD_ENV, saved_db_password)


# Fixed demo identities for the owned-keys app. The owner is a NON-admin human principal
# (scopes ``read``+``mint``, no ``*`` and no jq condition) so its examples can show the
# real owner-attenuation behaviour: it mints only within its own scopes, and asking for
# a scope it does not hold is rejected at mint time. The owner's credential is its login
# session (an api key is always owned, and an owned key never mints); the opaque token
# carries the documented ``tai-sess-`` prefix.
_OWNER_ID = "maya"
_OWNER_SESSION = "tai-sess-maya-demo-session"
# The one owned key the inspect/share examples use, minted for the owner at boot.
_OWNED_KEY_ID = "maya-device"
_SESSION_PROVIDER_NAME = "session"


def _register_owner_session_provider() -> None:
    """Register a minimal accounts-style session provider beside the api-key provider.

    It resolves the owner's one demo session token to the owner principal with no
    claims (a session is a top-level principal) and answers ``None`` for any other
    token, so the verifier chain moves on to the api-key provider.
    """
    from tai42_contract.access_control import AuthIdentity, IdentityProvider
    from tai42_kit.access_control import registry

    class _OwnerSessionProvider(IdentityProvider):
        async def validate_token(self, token: str) -> AuthIdentity | None:
            if token == _OWNER_SESSION:
                return AuthIdentity(user_id=_OWNER_ID, claims={})
            return None

    registry.register_identity_provider(_SESSION_PROVIDER_NAME, lambda _settings: _OwnerSessionProvider())


def _mint_owned_key() -> str:
    """Mint the owner's demo key through the platform's own mint path and return the raw ``sk-…``.

    Runs after the storage seams point at the fakes, so the identity record and the
    policy row (both carrying the owner) land in the fake stores in the exact shape
    every real mint writes.
    """
    from tai42_skeleton.access_control.management import add_user_api_key

    raw_key, _body, _fingerprint = asyncio.run(
        add_user_api_key(_OWNED_KEY_ID, "the owner's device key", ["read"], owner_user_id=_OWNER_ID)
    )
    return raw_key


def _seed_owned_keys_store() -> tuple[FakeRedis, FakeAccessControlPg]:
    """Seed the fake Redis and fake policy store for the owned-key example.

    Redis starts empty (the owned key is minted into it at boot); the policy store
    gets the routes the owner reaches and the owner's non-admin scope set.
    """
    from tests.access_control.conftest import (  # type: ignore[import-not-found]
        FakeAccessControlPg,
        FakeRedis,
    )

    fake_redis = FakeRedis(strings={}, hashes={})
    fake_pg = FakeAccessControlPg()
    # Map the two authed doors the owner reaches to a scope the owner holds; the mint
    # also validates that a granted scope exists (has a url mapping), so ``read`` gets
    # a mapping too. ``/api/auth/me`` is an always-allowed carve-in — no mapping.
    fake_pg.add_route("/api/auth/api-keys", "mint")
    fake_pg.add_route("/api/auth/claim-links", "mint")
    fake_pg.add_route("/api/tools", "read")
    # The owner is a top-level principal: its policy carries no owner claim, so its
    # session may mint keys owned by itself. The mint's owner-exists check reads its
    # principal row.
    fake_pg.add_principal(_OWNER_ID, kind="human", display_name="Maya")
    fake_pg.add_policy(_OWNER_ID, scopes=["read", "mint"])
    return fake_redis, fake_pg


def _swap_owned_keys_seams(fake_redis: FakeRedis, fake_pg: FakeAccessControlPg) -> list[tuple[object, str, object]]:
    """Point the five ``client_ctx`` seams the owned-key routes reach at the fakes.

    Redirects the key-policy history store to the in-memory generic store so the
    mint write-through runs offline. Returns the ``(object, attr, original)``
    restore list.
    """
    from tai42_identity_redis import redis_api_key_provider as provider_module
    from tai42_skeleton.access_control import claim_links as claim_links_module
    from tai42_skeleton.access_control import management as management_module
    from tai42_skeleton.access_control import policy as policy_module
    from tai42_skeleton.access_control import store as store_module
    from tai42_skeleton.access_control.policy_store import AcPolicyStore
    from tai42_skeleton.operations import api_keys as ops_api_keys
    from tests.access_control.conftest import make_client_ctx, make_pg_ctx  # type: ignore[import-not-found]
    from tests.access_control.test_policy_store import _MemStore  # type: ignore[import-not-found]

    redis_ctx = make_client_ctx(fake_redis)
    pg_ctx = make_pg_ctx(fake_pg)
    seams: list[tuple[object, str, object]] = []
    for module in (policy_module, provider_module, claim_links_module, management_module):
        seams.append((module, "client_ctx", module.client_ctx))
        module.client_ctx = redis_ctx  # type: ignore[attr-defined]
    seams.append((store_module, "client_ctx", store_module.client_ctx))
    store_module.client_ctx = pg_ctx  # type: ignore[attr-defined]

    # A mint writes the new key's policy to durable version history through the
    # generic versioned store, which would otherwise reach for a real Postgres pool.
    # Point that factory at the skeleton's own in-memory generic store (the pattern
    # its own key-create tests use), so the history write-through runs offline.
    seams.append((ops_api_keys, "ac_policy_store", ops_api_keys.ac_policy_store))
    ops_api_keys.ac_policy_store = lambda: AcPolicyStore(_MemStore())  # type: ignore[attr-defined]
    return seams


def _pin_projection_seams() -> list[tuple[object, str, object]]:
    """Pin the projection's live-registry seams to controlled values and reset its cache.

    Pins the tool/agent/sub-MCP surfaces a full app would populate; the
    store-backed route derivation stays real. Returns the ``(object, attr,
    original)`` restore list.
    """
    from tai42_skeleton.access_control import projection as projection_module

    async def _empty_sub_mcp() -> dict:
        return {}

    async def _empty_tools() -> list[str]:
        return []

    def _projection_routes() -> list[SimpleNamespace]:
        return [
            SimpleNamespace(path="/api/auth/me", methods=["GET"]),
            SimpleNamespace(path="/api/tools", methods=["GET"]),
        ]

    seams: list[tuple[object, str, object]] = []
    for name, value in (
        ("_registry_routes", _projection_routes),
        ("_sub_mcp_routes", _empty_sub_mcp),
        ("_all_registry_tools", _empty_tools),
        ("_all_agent_names", list),
    ):
        seams.append((projection_module, name, getattr(projection_module, name)))
        setattr(projection_module, name, value)
    projection_module.reset_projection_cache()
    return seams


@contextmanager
def owned_keys_app() -> Iterator[dict[str, str]]:
    """Boot the real owned-key delegation routes on a localhost socket.

    Runs behind the real access-control chain over the fake store. Serves the
    three delegation doors — ``GET /api/auth/me`` (the capability
    projection), ``POST /api/auth/api-keys`` (mint), ``POST /api/auth/claim-links``
    (create a claim link), and the public ``POST /api/login/claim`` (exchange) — mounted
    as their REAL route handlers behind ``AuthAdapter``'s middleware, so an example
    observes the real projection, the real owner-scope cap, and the real single-use
    claim burn. Yields ``TAI_BASE_URL``/``TAI_SERVER_URL``, the owner's login session as
    ``TAI_API_KEY`` and one key minted for the owner as ``TAI_OWNED_KEY``, so both a
    ``curl`` and a ``tai`` command run against it.

    Like :func:`ac_app` only the Redis/Postgres storage seams are faked, plus the owner's
    login session, which a minimal session provider registered beside the api-key
    provider resolves (the accounts sign-in flow is outside this boot). The capability
    projection additionally reaches into a fully-built app's tool/agent/sub-MCP
    registries, which this minimal boot does not populate, so the four live-registry
    projection seams are pinned to controlled values exactly as the projection's own unit
    tests do — the route derivation still runs for real against the seeded store.
    """
    from starlette.applications import Starlette
    from starlette.routing import Route
    from tai42_contract.app import tai42_app
    from tai42_skeleton.access_control import projection as projection_module
    from tai42_skeleton.access_control.adapter import AuthAdapter
    from tai42_skeleton.access_control.settings import AccessControlSettings
    from tai42_skeleton.app.route_registry import load_api_routes
    from tests.access_control.conftest import _FakeApp  # type: ignore[import-not-found]

    # Snapshot every process-global this fixture mutates BEFORE mutating any of it, so the
    # finally restores exactly. ``seams`` is a list of ``(object, attr, original)`` so one
    # restore loop covers both the ``client_ctx`` module seams and the projection's
    # live-registry seams. Every mutation happens inside the try, so restore runs on EVERY
    # exit path — including the uvicorn-startup-timeout raise.
    saved_registry = _snapshot_identity_registry()
    saved_db_password = os.environ.get(_DEFAULT_DATABASE_PASSWORD_ENV)
    seams: list[tuple[object, str, object]] = []
    server = None
    thread = None
    try:
        os.environ[_DEFAULT_DATABASE_PASSWORD_ENV] = _DEFAULT_DATABASE_PASSWORD

        _register_default_identity_provider()
        _register_owner_session_provider()

        # The delegation routes register onto the app's HTTP surface at import; importing
        # them needs a bound app. ``load_api_routes`` binds the skeleton's own offline
        # capture app and imports every router module, so the real handlers become
        # importable without booting a server.
        load_api_routes()
        from tai42_skeleton.routers import api_keys as api_keys_router
        from tai42_skeleton.routers import login as login_router

        # Rebind the storage-bearing fake app the auth backend + projection render the
        # (empty) policy condition through at request time.
        tai42_app.bind(_FakeApp())

        settings = AccessControlSettings()
        fake_redis, fake_pg = _seed_owned_keys_store()
        seams = _swap_owned_keys_seams(fake_redis, fake_pg)
        seams += _pin_projection_seams()
        owned_key = _mint_owned_key()

        app = Starlette(
            routes=[
                Route("/api/auth/me", api_keys_router.get_me, methods=["GET"]),
                Route("/api/auth/api-keys", api_keys_router.create_api_key, methods=["POST"]),
                Route("/api/auth/claim-links", api_keys_router.create_claim_link, methods=["POST"]),
                Route("/api/login/claim", login_router.exchange_claim_token, methods=["POST"]),
            ],
            middleware=AuthAdapter(settings).get_middleware(),
        )
        # Assign the handles BEFORE awaiting startup so a startup-timeout raise still
        # leaves them in scope for the finally to stop the server.
        server, thread, port = _start_uvicorn(app)
        _await_started(server, "owned_keys_app")

        base_url = f"http://127.0.0.1:{port}"
        yield {
            "TAI_BASE_URL": base_url,
            "TAI_SERVER_URL": base_url,
            "TAI_API_KEY": _OWNER_SESSION,
            "TAI_OWNED_KEY": owned_key,
        }
    finally:
        _stop_uvicorn(server, thread)
        for obj, attr, original in seams:
            setattr(obj, attr, original)
        # projection_module may be unbound if an import failed before it — nothing to reset.
        with suppress(NameError):
            projection_module.reset_projection_cache()
        tai42_app.bind(None)
        _restore_identity_registry(saved_registry)
        _restore_env(_DEFAULT_DATABASE_PASSWORD_ENV, saved_db_password)


@contextmanager
def no_fixture() -> Iterator[dict[str, str]]:
    """No server needed (a self-contained CLI or a YAML validation).

    Yields no extra environment.
    """
    yield {}


# Fixture name (declared as ``#| fixture: <name>`` in an example) -> factory. The
# harness boots the named fixture once and runs every example that references it
# inside that live context.
FIXTURES: dict[str, Callable[[], object]] = {
    "none": no_fixture,
    "ac_app": ac_app,
    "owned_keys_app": owned_keys_app,
}
