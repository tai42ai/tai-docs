#| fixture: owned_keys_app
#| expect_exit: 0
#| expect_stdout_contains: claimed=maya second=refused
set -e
# 1. Mint a one-time claim link that carries a key you already hold to another device.
#    The token rides the URL fragment (/login#claim=<token>) and is single-use.
token=$(tai keys claim-link "$TAI_API_KEY" --json \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')

# 2. On the other device, exchange the token for the key — a public, credential-free
#    door. `tai auth claim` accepts the bare token or the whole claim URL.
claimed=$(tai auth claim "$token" --json \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["user_id"])')

# 3. The link is single-use: exchanging the same token again is refused with a uniform
#    404 (a used, unknown, or expired token are indistinguishable to the caller).
if tai auth claim "$token" >/dev/null 2>&1; then second="reused"; else second="refused"; fi

echo "claimed=$claimed second=$second"
