#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: --answer
# Answer a pending in-client question. The value is JSON: a string for text and
# select, a bool for confirm, an object for form.
tai interactions answer --help
