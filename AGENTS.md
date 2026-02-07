Use TDD for new features and bug fixes.
Red, green, refactor.
Commit often.

Note to future self: When running tests here, use the repo's existing venv (commonly ./venv) rather than the system Python. .venv may not have deps or network access.

When I report a bug, don't start by trying to fix it.
Instead, start by writing a test that reproduces the bug.
Then, try to fix the bug and prove it with a passing test.
