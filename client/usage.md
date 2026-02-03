# Integration Guide

This guide covers how to integrate the cideldill client into your Python applications for remote debugging.

In this document, `/path/to/cideldill/client` refers to the directory that contains this usage.md file.

---

## Dependencies

The cideldill client package has minimal dependencies:

| Package | Required Version | Notes |
|---------|------------------|-------|
| dill | >=0.3.6 | Serialization |
| requests | >=2.31.0 | HTTP client |

The server package (which you run separately) additionally requires `flask` and `pygments`.

---

## Integration Options

### Option 1: Editable Install (Recommended)

Install the client as an editable package in your application's virtual environment.

```bash
pip install -e /path/to/cideldill/client
```

**Pros:**
- Changes to /path/to/cideldill/client are immediately available without reinstalling
- Standard Python packaging approach
- Full IDE support (autocomplete, go-to-definition)

**Cons:**
- Must install in each venv separately

---

### Option 2: PYTHONPATH Manipulation

Add the client source to `PYTHONPATH` at runtime or in your shell config.

```bash
export PYTHONPATH="/path/to/cideldill/client/src:$PYTHONPATH"
```

**Pros:**
- No installation required
- Instant changes reflected
- Easy to toggle on/off

**Cons:**
- Non-standard; may confuse tooling (linters, type checkers)
- Must remember to set for every shell/environment

---

### Option 3: Symlink in Site-Packages

Create a symlink from your venv's site-packages to the client source.

```bash
ln -s /path/to/cideldill/client/src/cideldill_client \
    /path/to/your-app/.venv/lib/python3.11/site-packages/cideldill_client
```

**Pros:**
- Changes reflected immediately
- No PYTHONPATH needed

**Cons:**
- Fragile; can break on venv recreation
- Must redo for each venv

---

### Option 4: Git Submodule

Add cideldill-client as a git submodule inside your project.

```bash
cd /path/to/your-app
git submodule add /path/to/cideldill/client libs/cideldill-client
pip install -e libs/cideldill-client
```

**Pros:**
- Version-controlled dependency
- Clear relationship between repos

**Cons:**
- Submodules add complexity
- Changes require submodule update commits

---

### Option 5: uv/pip Workspace

Use `uv` workspaces or similar tools to manage both repos as a unified workspace.

In your `pyproject.toml`:
```toml
[tool.uv.sources]
cideldill-client = { path = "/path/to/cideldill/client", editable = true }
```

**Pros:**
- Modern, clean dependency management
- Works well with monorepo setups

**Cons:**
- Requires workspace configuration
- More setup overhead

---

### Option 6: Conditional Import

Add conditional debug integration that only activates via environment variable.

```python
import os
if os.getenv("CIDELDILL_ENABLED"):
    from cideldill_client import with_debug
    with_debug("ON")
```

Combine with any of the above options for the actual import path.

**Pros:**
- Debug code doesn't affect production
- Easy to toggle without code changes

**Cons:**
- Requires code changes in your application
- Still need one of the other options for the import to work

---

## Summary

| Option | Best For |
|--------|----------|
| 1. Editable Install | IDE integration, standard workflow |
| 2. PYTHONPATH | Quick experiments |
| 3. Symlink | Hacky but works |
| 4. Git Submodule | Version-controlled dependency |
| 5. uv Workspace | Monorepo setups |
| 6. Conditional Import | Production safety toggle |

**Recommendation:** Use **Option 1 (Editable Install)** for the best developer experience with full IDE support.

---

## Quick Start

```bash
# 1. Install client in your app's venv
source /path/to/your-app/.venv/bin/activate
pip install -e /path/to/cideldill/client

# 2. Start the server (in a separate terminal, from /path/to/cideldill/server)
cd /path/to/cideldill/server && source venv/bin/activate
python -m cideldill_server --port 5174

# 3. In your application code:
from cideldill_client import with_debug
with_debug("ON")

# Wrap functions/objects you want to debug
my_function = with_debug(my_function)
```

See also:
- [with_debug API Reference](../docs/with_debug_api.md)
- [Breakpoints Web UI](../docs/breakpoints_web_ui.md)
