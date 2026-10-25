#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: TAI_BUS_REDIS_URL
# Run multiple worker processes with -w/--workers. Stateful HTTP transports refuse
# more than one worker; --stateless-http lifts that restriction for http /
# streamable-http. More than one worker also REQUIRES the worker bus — set
# TAI_BUS_REDIS_URL, or sibling workers would serve stale config after a reload
# with no channel to converge on — and the shared SUB_MCP_REDIS_URL and
# HOOKS_REDIS_URL stores (TAI_DEFAULT_REDIS_URL stands in for all three), so sub-MCP
# registrations and hooks are shared across workers. Each worker checks them at its
# boot, after the stored env is applied, and tai serve exits non-zero on a refusal.
tai serve --help
