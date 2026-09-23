#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --params
# Register a hook by passing the whole HookParams record as one --params JSON
# object (name, topic, tool, tool_kwargs, an optional condition, and the door-contract
# jqs start_expr/cancel_expr/resume_expr/extras_expr).
tai hooks register --help
