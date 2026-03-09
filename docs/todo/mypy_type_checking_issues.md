# Mypy Static Type Checking Issues

**Date:** 2026-03-10
**Status:** Pending
**Priority:** Medium

## Overview

This document tracks type checking issues found by `mypy` in the `gns3_copilot` module. These issues should be addressed to improve type safety and catch potential bugs at development time.

## How to Run Type Checking

```bash
# Install mypy
pip install mypy

# Run type checking on gns3_copilot module
mypy gns3server/agent/gns3_copilot/

# Install missing type stubs
mypy --install-types
pip install types-requests
```

## Issues Summary

### Total: 35 Type Errors

| File | Error Count | Priority |
|------|-------------|----------|
| chat_sessions_repository.py | 8 | High |
| context_manager.py | 5 | High |
| agent_service.py | 5 | High |
| gns3_topology_reader.py | 2 | Medium |
| message_converters.py | 1 | Medium |
| connector_factory.py | 1 | Medium |
| custom_gns3fy.py | Missing stubs | Low |
| display_tools_nornir.py | Missing stubs | Low |
| config_tools_nornir.py | Missing stubs | Low |

## Detailed Issues

### 1. chat_sessions_repository.py (8 errors)

**Lines 157, 234, 279, 283, 287, 291, 295**

#### Error 1: Return value type mismatch (Line 157)
```python
# Issue: Returning ChatSession | None, but function expects ChatSession
error: Incompatible return value type (got "ChatSession | None", expected "ChatSession")
error: Argument 1 to "get_session_by_id" has incompatible type "int | None"; expected "int"
```

**Fix:** Add proper null checks and type guards

#### Error 2: List append type mismatch (Lines 234, 279, 283, 287, 291, 295)
```python
# Issue: Appending int to list[str]
error: Argument 1 to "append" of "list" has incompatible type "int"; expected "str"
```

**Fix:** Convert integers to strings before appending, or change list type annotation

---

### 2. context_manager.py (5 errors)

**Lines 139, 145, 156, 167, 171**

```python
# Issue: Unsupported indexed assignment on Collection[str]
error: Unsupported target for indexed assignment ("Collection[str]")
```

**Problem:** `Collection[str]` is a read-only protocol, doesn't support item assignment.

**Fix:** Change type annotation to `List[str]` or `MutableSequence[str]`

---

### 3. agent_service.py (5 errors)

**Lines 267, 617, 634, 653, 675**

```python
# Issue: Passing Connection | None to function expecting Connection
error: Argument 1 to "ChatSessionsRepository" has incompatible type "Connection | None"; expected "Connection"
```

**Fix:** Add null checks before passing connection parameter, or use assertion

---

### 4. gns3_topology_reader.py (2 errors)

**Lines 137, 138**

```python
# Issue: len() argument has incompatible union type
error: Argument 1 to "len" has incompatible type "dict[Any, Any] | str | list[tuple[str, str, str, str]] | None"; expected "Sized"
```

**Fix:** Add null checks and type narrowing before calling `len()`

---

### 5. message_converters.py (1 error)

**Line 151**

```python
# Issue: List type assignment mismatch
error: Incompatible types in assignment (expression has type "list[dict[str, Any]]", variable has type "list[ToolCall]")
```

**Fix:** Either convert dict list to ToolCall list, or change variable type annotation

---

### 6. connector_factory.py (1 error)

**Line 368**

```python
# Issue: Calling split() on str | None without null check
error: Item "None" of "str | None" has no attribute "split"
```

**Fix:** Add null check before calling `split()` method

---

### 7. Missing Type Stubs (Low Priority)

The following third-party libraries lack type stubs:

- **requests** → Install: `pip install types-requests`
- **netmiko** → No official stubs available
- **nornir_netmiko** → No official stubs available

**Recommendation:** Create inline type ignores or stub files for these libraries.

---

## Recommended Fix Strategy

### Phase 1: High Priority (Critical Type Safety Issues)

1. **chat_sessions_repository.py**
   - Fix null safety issues
   - Ensure proper type conversions for list operations

2. **context_manager.py**
   - Change `Collection[str]` to `List[str]` for mutable collections

3. **agent_service.py**
   - Add null checks for database connections

### Phase 2: Medium Priority (Type Annotations)

4. **gns3_topology_reader.py**
   - Add type narrowing for union types

5. **message_converters.py**
   - Fix type compatibility between dict and ToolCall

6. **connector_factory.py**
   - Add null checks before method calls

### Phase 3: Low Priority (Third-party Stubs)

7. Install available type stubs (`types-requests`)
8. Add `# type: ignore` comments for unavoidable third-party issues

---

## Mypy Configuration

Consider adding a `mypy.ini` or `pyproject.toml` configuration:

```toml
[tool.mypy]
python_version = "3.13"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # Enable gradually
ignore_missing_imports = true    # For third-party libs

[[tool.mypy.overrides]]
module = "gns3server.agent.gns3_copilot.*"
disallow_untyped_defs = true
```

---

## Resources

- [Mypy Documentation](https://mypy.readthedocs.io/)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [Mypy Error Codes](https://mypy.readthedocs.io/en/stable/error_code_list.html)

---

## Notes

- All type issues are in the `gns3_copilot` module
- No type errors found in core GNS3 server code during this check
- Consider enabling type checking in CI/CD pipeline
- Type checking helps catch bugs before runtime
