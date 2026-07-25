#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --kw
# Run a registered tool, passing its arguments as repeatable --kw key=value pairs
# (each value parsed as JSON, falling back to the literal string) or as one JSON
# object with --kwargs.
tai tools run --help
