#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: delete-dir
# The storage group inspects and mutates the active storage provider's resources:
# info / list / stat / download / upload / delete / delete-dir.
tai storage --help
