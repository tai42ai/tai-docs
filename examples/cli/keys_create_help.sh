#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --scope
# The api-key create command grants scopes with a repeatable --scope flag.
tai keys create --help
