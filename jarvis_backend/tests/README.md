# JARVIS Backend Tests

Automated test suite for the JARVIS backend modules using [pytest](https://docs.pytest.org/).

## Running the tests

With the project virtualenv active, from the project root:

```bash
pytest jarvis_backend/tests/
```

From inside `jarvis_backend/` you can also run:

```bash
pytest
```

## Requirements

`pytest` must be installed. It is declared in `jarvis_backend/requirements.txt`
under the "Dev / testing" section. To install it in the project venv:

```bash
venv/bin/pip install -r jarvis_backend/requirements.txt
```

## What is covered

- `test_documents_module.py` — path-traversal rejection (absolute paths, `../`,
  symlink escapes), allowed/blocked file extensions, and overwrite confirmation.
- `test_system_actions.py` — command whitelist and rejection of shell
  metacharacters (`;`, `&&`, `|`, backticks, etc.).
- `test_memory.py` — mail session creation, expiry filtering, and cleanup of
  expired sessions.

## Config

`jarvis_backend/pytest.ini` sets `testpaths = tests` and adds `pythonpath = .`
so the `modules` package is importable when running pytest from `jarvis_backend/`.
