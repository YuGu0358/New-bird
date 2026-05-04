# Phase 9 — Code Editor + Sandboxed Strategy Upload

**Goal:** Let the user upload their own Python `Strategy` subclass, validate it for safety, persist it, and register it into the live `StrategyRegistry`. The upload-validate-register pipeline is the missing piece that turns this platform into a true "I write my own quant" tool.

**Architecture:**

```
                                         POST /api/code/upload
                                            ┌──────────────┐
                       user-supplied .py → │ AST validator│ → reject dangerous imports / patterns
                                            └──────┬───────┘
                                                   │ pass
                                            ┌──────▼───────┐
                                            │ Sandbox      │ exec(compile(code, ...), restricted_globals)
                                            │ loader       │ — finds Strategy subclass in namespace
                                            │              │ — calls @register_strategy(name)
                                            └──────┬───────┘
                                                   │
                                            ┌──────▼───────┐
                                            │ user_strategies table
                                            │ — code source / status / metadata
                                            └──────┬───────┘
                                                   │
                                            On startup: re-load all rows → register again
```

**Tech Stack:** stdlib `ast` + `compile` + `exec`. No new deps.

**Out of scope:**
- Subprocess-level isolation (current AST whitelist is "trust-but-verify" — a determined attacker could probably break out; this is meant for personal use, not multi-tenant)
- Live debug / breakpoints
- Frontend Code page implementation — backend only in P9; frontend wiring with QuantLib + AI Council comes in a final frontend pass per user direction

---

## File Structure

### New
| Path | Responsibility |
|---|---|
| `backend/core/code_loader/__init__.py` | Public API |
| `backend/core/code_loader/validator.py` | `validate_strategy_source(code)` AST whitelist guard |
| `backend/core/code_loader/sandbox.py` | `load_strategy_from_source(code, slot_name)` — exec + register |
| `backend/app/services/code_service.py` | DB CRUD + delegate to validator/sandbox |
| `backend/app/models/code.py` | API request/response models |
| `backend/app/routers/code.py` | 5 endpoints |

### Modified
| File | Change |
|---|---|
| `backend/app/db/tables.py` | Add `UserStrategy` table |
| `backend/app/db/__init__.py` | Re-export `UserStrategy` |
| `backend/app/models/__init__.py` | Re-export new models |
| `backend/app/main.py` | Register `code_router` + on-startup `reload_user_strategies()` |
| `backend/tests/test_openapi_parity.py` | Add 5 routes |

### New tests
| Path | Coverage |
|---|---|
| `backend/tests/test_code_validator.py` | Whitelist allows clean code; rejects `import os` / `subprocess` / `__import__` / `eval` / `open` / `exec` |
| `backend/tests/test_code_sandbox.py` | Loads a clean fixture strategy and registers it; rejects bad code |
| `backend/tests/test_code_service.py` | DB persist + reload round-trip |
| `backend/tests/test_app_smoke.py` (append) | List endpoint smoke |

---

## Pre-flight

- [ ] Baseline:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **169 passed**.

- [ ] Branch:
```bash
cd ~/NewBirdClaude
git checkout feat/p8-quantlib
git checkout -b feat/p9-code-editor
```

---

## Task 1: AST validator (TDD)

**Files:**
- Create: `backend/core/code_loader/__init__.py`
- Create: `backend/core/code_loader/validator.py`
- Create: `backend/tests/test_code_validator.py`

The validator walks the AST and enforces:

1. **Import whitelist:** only `core.strategy.*`, `core.broker.*`, `app.models.*`, `app.models.StrategyExecutionParameters`, `numpy`, `pandas`, `math`, `statistics`, `datetime`, `typing`, `dataclasses`, `__future__`, `decimal`, `enum`, `re`.
2. **Forbidden builtins:** `exec`, `eval`, `compile`, `__import__`, `open`, `input`, `breakpoint`, `vars`, `globals`, `locals`.
3. **Forbidden attribute names:** anything matching `__class__`, `__bases__`, `__subclasses__`, `__globals__`, `__code__`, `__builtins__`, `mro`.
4. **Code size:** rejects > 100,000 characters.
5. **Must contain a class that subclasses `Strategy`** (string match on base name in P9; full MRO check after exec).

Write tests first, then implementation. Each error case is its own test.

The actual code patterns are extensive — see plan execution notes.

---

## Task 2: Sandbox loader (TDD)

**Files:**
- Create: `backend/core/code_loader/sandbox.py`
- Create: `backend/tests/test_code_sandbox.py`

Given validated source + a slot name, the loader:

1. Compiles into a code object.
2. Builds a restricted globals dict with allowed builtins and pre-imported safe modules.
3. `exec`s the code — the `@register_strategy` decorator runs and inserts into `default_registry`.
4. Verifies that exactly one new strategy was registered, and its name matches the slot.
5. Returns the registered class.

If validation passes but exec fails, raises `SandboxLoadError` with the underlying exception.

If the code re-registers an existing name, raises `StrategyAlreadyRegisteredError`. To allow re-uploads of edits, the service first removes the prior class from the registry.

---

## Task 3: DB + service + reload-on-boot

**Files:**
- Modify: `backend/app/db/tables.py` — add `UserStrategy`
- Modify: `backend/app/db/__init__.py` — re-export
- Create: `backend/app/services/code_service.py`
- Create: `backend/tests/test_code_service.py`

`UserStrategy` columns:
```
id, slot_name (unique, e.g. "user_strategy_1"), display_name,
description, source_code (Text), status ("active"|"disabled"|"failed"),
last_error, created_at, updated_at
```

`code_service` exposes:
- `save_user_strategy(session, *, slot_name, display_name, description, source_code)` → validates → loads → persists
- `list_user_strategies(session)` → list of dicts
- `get_source(session, strategy_id)` → raw code
- `delete_user_strategy(session, strategy_id)` → unregister + delete row
- `reload_all_user_strategies(session)` → on boot, walk all "active" rows and re-register

---

## Task 4: API models + router

**Endpoints:**
- `GET /api/code/strategies` — list
- `POST /api/code/upload` — upload + validate + register
- `GET /api/code/strategies/{id}/source` — return code
- `DELETE /api/code/strategies/{id}` — remove
- `POST /api/code/strategies/{id}/reload` — re-validate + re-register existing row

---

## Task 5: Wire reload on app startup

In `app/main.py`, the existing `lifespan` adds:
```python
async with AsyncSessionLocal() as session:
    await code_service.reload_all_user_strategies(session)
```
so user-uploaded strategies are available right after restart.

---

## Task 6: Final verify + push

- Full pytest green
- Live boot: upload an example strategy, list it, fetch source, delete

---

## Done-criteria

- All on `feat/p9-code-editor`, branched off `feat/p8-quantlib`.
- `pytest tests/` ≥ **180 passed**.
- 5 new routes; parity locked.
- User can write Python `@register_strategy("name")` class and POST it; it shows up in `/api/strategies/registered` and is backtest-runnable.

After Phase 9, **the entire backend roadmap is complete (P0–P9)**. Frontend wires the remaining 3 placeholder tabs (AI Council ✓ done, QuantLib, Code) in a final frontend pass.
