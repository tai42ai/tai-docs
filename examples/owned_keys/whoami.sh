#| fixture: owned_keys_app
#| expect_exit: 0
#| expect_stdout_contains: maya-device
set -e
# Run as the owned key: $TAI_OWNED_KEY holds a key the owner minted.
# `tai auth whoami` prints the caller's derived capability projection — the routes,
# tools, and agents this key can reach right now. (`mintable` is the deployment's
# flag, not this key's: an owned key still gets a 403 on any mint.)
TAI_API_KEY="$TAI_OWNED_KEY" tai auth whoami

# The same projection straight from the HTTP door the CLI wraps.
curl -sS -H "X-Api-Key: $TAI_OWNED_KEY" "$TAI_BASE_URL/api/auth/me"
