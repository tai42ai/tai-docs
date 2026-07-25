#| fixture: owned_keys_app
#| expect_exit: 0
#| expect_stdout_contains: maya
set -e
# `tai auth whoami` prints the caller's derived capability projection — the routes,
# tools, and agents this key can reach right now, plus whether it may mint keys.
tai auth whoami

# The same projection straight from the HTTP door the CLI wraps.
curl -sS -H "X-Api-Key: $TAI_API_KEY" "$TAI_BASE_URL/api/auth/me"
