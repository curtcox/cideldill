# Cleanup Findings

## Bugs / Risks
~~CIDStore.get_many() builds an invalid SQL `IN ()` when `cids` is empty, which can raise an exception in `get_many()` and `missing()`. Add an early return for empty inputs. (`server/src/cideldill_server/cid_store.py`)~~

## Backward-Compatibility Cleanup (Not Needed Yet)
~~Remove compatibility aliases `CIDMismatchError` and `CIDNotFoundError` in both client and server exceptions. (`client/src/cideldill_client/exceptions.py`, `server/src/cideldill_server/exceptions.py`)~~
~~Remove acceptance of behavior value `"continue"` in breakpoint behaviors/defaults; standardize on `"stop" | "go" | "yield"`. (`server/src/cideldill_server/breakpoint_manager.py`)~~
~~Revisit `_reconstruct_placeholder()` fallback keys (`type`, `id`, `repr`, `error`, `attempts`) that appear to support older placeholder schemas. Drop if no legacy data needs to load. (`client/src/cideldill_client/custom_picklers.py`)~~
~~Consider removing or renaming the explicit “compatibility” tests if they are only covering legacy behavior. (`tests/unit/test_with_debug_compatibility.py`)~~

## Complexity / Maintainability
~~Client and server `serialization.py` are nearly identical; consider a shared module or extraction to avoid divergence and duplicated fixes. (`client/src/cideldill_client/serialization.py`, `server/src/cideldill_server/serialization.py`)~~
~~`html_generator.py` and `source_viewer.py` embed large, mostly duplicated HTML/CSS/JS strings in Python, which is hard to maintain. Consider moving templates/static assets to `static/` and using a templating layer or Jinja templates. (`server/src/cideldill_server/html_generator.py`, `server/src/cideldill_server/source_viewer.py`)~~

## Tests Missing / Under-Tested
~~Add unit tests for `CIDStore` behavior: `get_many()` empty input, `missing()` empty input, `store_many()` mismatch handling, `stats()`. (`server/src/cideldill_server/cid_store.py`)~~
~~Add tests for server-side serialization (mirror the client tests or share the test suite). (`server/src/cideldill_server/serialization.py`)~~
~~Add tests for HTML generation and source viewer output (smoke tests for key HTML sections, links, and escaping). (`server/src/cideldill_server/html_generator.py`, `server/src/cideldill_server/source_viewer.py`)~~
