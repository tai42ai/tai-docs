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

import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace

# The fakes live in the skeleton's test tree. The docs scripts run from the
# skeleton virtualenv (cwd = tai-skeleton), but resolve the skeleton root
# explicitly so ``import tests…`` works regardless of the invoking cwd.
_SKELETON_ROOT = Path(__file__).resolve().parent.parent.parent / "tai-skeleton"
if _SKELETON_ROOT.is_dir() and str(_SKELETON_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKELETON_ROOT))


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# Fixed demo credentials + scope for the access-control app. The allowed key's
# policy carries the route's scope (→ 200); the denied key authenticates but its
# policy lacks the scope (→ 403); no key at all is rejected 401.
_ALLOW_KEY = "ac-allow-demo-key"
_DENY_KEY = "ac-deny-demo-key"
_SCOPE = "demo-scope"
_GUARDED_PATH = "/guarded"


@contextmanager
def ac_app() -> Iterator[dict[str, str]]:
    """Boot the real access-control middleware chain over a fake store and serve
    it on a localhost socket. Yields ``TAI_BASE_URL`` + an allowed and a denied
    api key so a ``curl`` example can observe a real 200 vs 403."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from tai_contract.access_control import registry
    from tai_contract.app import tai_app
    from tai_identity_redis import redis_api_key_provider as provider_module
    from tai_identity_redis.redis_api_key_provider import RedisApiKeyProvider
    from tai_kit.utils.data.string_util import hash_api_key
    from tai_skeleton.access_control import policy as policy_module
    from tai_skeleton.access_control import store as store_module
    from tai_skeleton.access_control import verifier as verifier_module
    from tai_skeleton.access_control.adapter import AuthAdapter
    from tai_skeleton.access_control.settings import AccessControlSettings
    from tests.access_control.conftest import (  # type: ignore[import-not-found]
        FakeAccessControlPg,
        FakeRedis,
        _FakeApp,
        make_client_ctx,
        make_pg_ctx,
    )

    # Snapshot the process-global state this fixture mutates BEFORE mutating any of
    # it, so the finally can restore exactly. Reading the snapshot is side-effect
    # free; every mutation (registry, bound app, client_ctx seams) happens inside
    # the try below, so the restore runs on EVERY exit — including the
    # uvicorn-startup-timeout path, which raises from inside the try.
    saved_registry = dict(registry._REGISTRY)
    seams: list[tuple[object, object]] = []
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    try:
        # The skeleton ships no concrete identity provider; a deployment lists one
        # in its manifest. Register the default "redis" provider the way a manifest
        # import would.
        registry._REGISTRY.clear()
        registry.register_identity_provider("redis", RedisApiKeyProvider)

        # The auth backend renders the (empty) policy condition through the bound app.
        tai_app.bind(_FakeApp())

        settings = AccessControlSettings()
        fake_redis = FakeRedis(
            hashes={
                f"{settings.key_prefix}{hash_api_key(_ALLOW_KEY)}": {
                    "user_id": "allowed-user",
                    "description": "allowed",
                },
                f"{settings.key_prefix}{hash_api_key(_DENY_KEY)}": {"user_id": "denied-user", "description": "denied"},
            },
        )
        fake_pg = FakeAccessControlPg()
        fake_pg.add_route(_GUARDED_PATH, _SCOPE)
        fake_pg.add_policy("allowed-user", scopes=[_SCOPE])
        fake_pg.add_policy("denied-user", scopes=[])

        redis_ctx = make_client_ctx(fake_redis)
        pg_ctx = make_pg_ctx(fake_pg)
        for module in (verifier_module, policy_module, provider_module):
            seams.append((module, module.client_ctx))
            module.client_ctx = redis_ctx  # type: ignore[attr-defined]
        seams.append((store_module, store_module.client_ctx))
        store_module.client_ctx = pg_ctx  # type: ignore[attr-defined]

        async def _guarded(_request):
            return PlainTextResponse("ok")

        app = Starlette(
            routes=[Route(_GUARDED_PATH, _guarded)],
            middleware=AuthAdapter(settings).get_middleware(),
        )
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("ac_app fixture: uvicorn did not start within 10s")
            time.sleep(0.02)

        yield {
            "TAI_BASE_URL": f"http://127.0.0.1:{port}",
            "TAI_API_KEY": _ALLOW_KEY,
            "TAI_DENIED_KEY": _DENY_KEY,
        }
    finally:
        # Restore is idempotent and covers every partial-setup path: stop the
        # server (if it was started), undo whichever seams were swapped, unbind the
        # app, and reinstate the identity registry.
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        for module, original in seams:
            module.client_ctx = original  # type: ignore[attr-defined]
        tai_app.bind(None)
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved_registry)


# Fixed demo credentials for the owned-keys app. The seeded key is a NON-admin owner
# (scopes ``read``+``mint``, no ``*`` and no jq condition) so its examples can show the
# real owner-attenuation behaviour: it mints only within its own scopes, and asking for
# a scope it does not hold is rejected at mint time.
_OWNER_KEY = "sk-owner-demo-key"
_OWNER_ID = "maya"


@contextmanager
def owned_keys_app() -> Iterator[dict[str, str]]:
    """Boot the real owned-key delegation routes behind the real access-control chain
    over the fake store, and serve them on a localhost socket.

    Serves the three delegation doors — ``GET /api/auth/me`` (the capability
    projection), ``POST /api/auth/api-keys`` (mint), ``POST /api/auth/claim-links``
    (create a claim link), and the public ``POST /api/login/claim`` (exchange) — mounted
    as their REAL route handlers behind ``AuthAdapter``'s middleware, so an example
    observes the real projection, the real owner-scope cap, and the real single-use
    claim burn. Yields ``TAI_BASE_URL``/``TAI_SERVER_URL`` and the owner's ``TAI_API_KEY``
    so both a ``curl`` and a ``tai`` command run against it.

    Like :func:`ac_app` only the Redis/Postgres storage seams are faked. The capability
    projection additionally reaches into a fully-built app's tool/agent/sub-MCP
    registries, which this minimal boot does not populate, so the four live-registry
    projection seams are pinned to controlled values exactly as the projection's own unit
    tests do — the route derivation still runs for real against the seeded store."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route
    from tai_contract.access_control import registry
    from tai_contract.app import tai_app
    from tai_identity_redis import redis_api_key_provider as provider_module
    from tai_identity_redis.redis_api_key_provider import RedisApiKeyProvider
    from tai_kit.utils.data.string_util import hash_api_key
    from tai_skeleton.access_control import claim_links as claim_links_module
    from tai_skeleton.access_control import management as management_module
    from tai_skeleton.access_control import policy as policy_module
    from tai_skeleton.access_control import projection as projection_module
    from tai_skeleton.access_control import store as store_module
    from tai_skeleton.access_control import verifier as verifier_module
    from tai_skeleton.access_control.adapter import AuthAdapter
    from tai_skeleton.access_control.policy_store import AcPolicyStore
    from tai_skeleton.access_control.settings import AccessControlSettings
    from tai_skeleton.app.route_registry import load_api_routes
    from tai_skeleton.operations import api_keys as ops_api_keys
    from tests.access_control.conftest import (  # type: ignore[import-not-found]
        FakeAccessControlPg,
        FakeRedis,
        _FakeApp,
        make_client_ctx,
        make_pg_ctx,
    )
    from tests.access_control.test_policy_store import _MemStore  # type: ignore[import-not-found]

    # Snapshot every process-global this fixture mutates BEFORE mutating any of it, so the
    # finally restores exactly. ``seams`` is a list of ``(object, attr, original)`` so one
    # restore loop covers both the ``client_ctx`` module seams and the projection's
    # live-registry seams. Every mutation happens inside the try, so restore runs on EVERY
    # exit path — including the uvicorn-startup-timeout raise.
    saved_registry = dict(registry._REGISTRY)
    seams: list[tuple[object, str, object]] = []
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    try:
        registry._REGISTRY.clear()
        registry.register_identity_provider("redis", RedisApiKeyProvider)

        # The delegation routes register onto the app's HTTP surface at import; importing
        # them needs a bound app. ``load_api_routes`` binds the skeleton's own offline
        # capture app and imports every router module, so the real handlers become
        # importable without booting a server.
        load_api_routes()
        from tai_skeleton.routers import api_keys as api_keys_router
        from tai_skeleton.routers import login as login_router

        # Rebind the storage-bearing fake app the auth backend + projection render the
        # (empty) policy condition through at request time.
        tai_app.bind(_FakeApp())

        settings = AccessControlSettings()
        fake_redis = FakeRedis(
            strings={},
            hashes={
                f"{settings.key_prefix}{hash_api_key(_OWNER_KEY)}": {
                    "user_id": _OWNER_ID,
                    "description": "owner key",
                },
            },
        )
        fake_pg = FakeAccessControlPg()
        # Map the two authed doors the owner reaches to a scope the owner holds; the mint
        # also validates that a granted scope exists (has a url mapping), so ``read`` gets
        # a mapping too. ``/api/auth/me`` is an always-allowed carve-in — no mapping.
        fake_pg.add_route("/api/auth/api-keys", "mint")
        fake_pg.add_route("/api/auth/claim-links", "mint")
        fake_pg.add_route("/api/tools", "read")
        # A non-admin owner: a plain scope set with no ``*`` and no jq condition.
        fake_pg.add_policy(_OWNER_ID, scopes=["read", "mint"])

        redis_ctx = make_client_ctx(fake_redis)
        pg_ctx = make_pg_ctx(fake_pg)
        for module in (
            verifier_module,
            policy_module,
            provider_module,
            claim_links_module,
            management_module,
            projection_module,
        ):
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

        # Pin the projection's live-registry seams (tool/agent/sub-MCP surfaces a full app
        # would populate) to controlled values; the store-backed route derivation is real.
        async def _empty_sub_mcp() -> dict:
            return {}

        async def _empty_tools() -> list[str]:
            return []

        def _projection_routes() -> list[SimpleNamespace]:
            return [
                SimpleNamespace(path="/api/auth/me", methods=["GET"]),
                SimpleNamespace(path="/api/tools", methods=["GET"]),
            ]

        for name, value in (
            ("_registry_routes", _projection_routes),
            ("_sub_mcp_routes", _empty_sub_mcp),
            ("_all_registry_tools", _empty_tools),
            ("_all_agent_names", list),
        ):
            seams.append((projection_module, name, getattr(projection_module, name)))
            setattr(projection_module, name, value)
        projection_module.reset_projection_cache()

        app = Starlette(
            routes=[
                Route("/api/auth/me", api_keys_router.get_me, methods=["GET"]),
                Route("/api/auth/api-keys", api_keys_router.create_api_key, methods=["POST"]),
                Route("/api/auth/claim-links", api_keys_router.create_claim_link, methods=["POST"]),
                Route("/api/login/claim", login_router.exchange_claim_token, methods=["POST"]),
            ],
            middleware=AuthAdapter(settings).get_middleware(),
        )
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("owned_keys_app fixture: uvicorn did not start within 10s")
            time.sleep(0.02)

        base_url = f"http://127.0.0.1:{port}"
        yield {
            "TAI_BASE_URL": base_url,
            "TAI_SERVER_URL": base_url,
            "TAI_API_KEY": _OWNER_KEY,
        }
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        for obj, attr, original in seams:
            setattr(obj, attr, original)
        # projection_module may be unbound if an import failed before it — nothing to reset.
        with suppress(NameError):
            projection_module.reset_projection_cache()
        tai_app.bind(None)
        registry._REGISTRY.clear()
        registry._REGISTRY.update(saved_registry)


@contextmanager
def no_fixture() -> Iterator[dict[str, str]]:
    """No server needed (a self-contained CLI or a YAML validation). Yields no
    extra environment."""
    yield {}


# Fixture name (declared as ``#| fixture: <name>`` in an example) -> factory. The
# harness boots the named fixture once and runs every example that references it
# inside that live context.
FIXTURES: dict[str, Callable[[], object]] = {
    "none": no_fixture,
    "ac_app": ac_app,
    "owned_keys_app": owned_keys_app,
}
