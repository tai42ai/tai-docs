#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --params
# Register a hook by passing the whole HookParams record as one --params JSON
# object (name, topic, tool, tool_kwargs, and an optional condition).
tai hooks register --help
