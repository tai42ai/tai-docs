#| fixture: ac_app
#| expect_exit: 0
#| expect_stdout_contains: 403
# A valid key whose policy lacks the route's scope is denied: 403.
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "X-Api-Key: $TAI_DENIED_KEY" \
  "$TAI_BASE_URL/guarded"
