#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: reload-config
# The fleet group is the operator's window onto the worker fleet: info (the
# registered backend's identity), workers (the live census — every process on
# the bus), and reload-config (soft-restart the fleet).
tai fleet --help
