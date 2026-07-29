#| fixture: ac_app
#| expect_exit: 0
#| expect_stdout_contains: 200
# A key whose policy grants the route's scope reaches the resource: 200.
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "X-Api-Key: $TAI_API_KEY" \
  "$TAI_BASE_URL/guarded"
