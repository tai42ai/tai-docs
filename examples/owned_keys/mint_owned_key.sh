#| fixture: owned_keys_app
#| expect_exit: 0
#| expect_stdout_contains: capped=200 excess=400
# An owner mints a capped key. A non-admin owner may grant only scopes it holds
# itself, and the new key is owned by the minter — the raw sk-… value is returned once.
capped=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$TAI_BASE_URL/api/auth/api-keys" \
  -H "X-Api-Key: $TAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "field-scanner", "description": "read-only field key", "scopes": ["read"]}')

# Asking for a scope the owner does not hold is rejected at mint time: a fixed 400,
# never a silently narrowed key.
excess=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$TAI_BASE_URL/api/auth/api-keys" \
  -H "X-Api-Key: $TAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "over-reach", "description": "over-scoped key", "scopes": ["read", "write"]}')

echo "capped=$capped excess=$excess"
