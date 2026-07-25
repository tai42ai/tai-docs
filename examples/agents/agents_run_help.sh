#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --input
# Every agent runs the same way: tai agents run <name> --input '<JSON>'. The input
# fields are the agent's own ToolInput; read one with tai tools schema <run-tool>.
tai agents run --help
