#| fixture: none
#| expect_exit: 0
#| expect_stdout_contains: set-version-tags
# The presets group carries the versioned-preset workflow plus the newer
# referees / validate / set-version-tags / rename subcommands.
tai presets --help
