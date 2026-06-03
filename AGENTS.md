# Repository Guidelines

## Project Shape

This repository is an AstrBot plugin that connects private and group chats to Hindsight Cloud long-term memory. It is intentionally standalone: do not modify AstrBot core and do not add a custom WebUI.

Key files:

- `main.py` contains the AstrBot plugin class, LLM hooks, and `/hindsight` command registration.
- `hindsight_client.py` wraps Hindsight Cloud REST calls with async `httpx`.
- `scope.py` builds private/group memory scopes and hashed tags.
- `memory_formatter.py` converts recall responses into temporary prompt text.
- `commands.py` owns local plugin state helpers and command support functions.
- `_conf_schema.json` defines AstrBot plugin configuration.
- `tests/` contains standalone `unittest` coverage.

## Development Commands

Run all tests:

```bash
python -m unittest discover -s tests
```

Check Python syntax:

```bash
python -m py_compile main.py commands.py hindsight_client.py memory_formatter.py scope.py
```

This repo may be owned by a different Windows user in sandboxed sessions. Use `git -c safe.directory=D:/Project/astrbot_plugin_hindsight_memory ...` for read-only git commands if normal `git status` fails.

## Implementation Notes

- Keep dependencies minimal. `requirements.txt` should only include dependencies the plugin truly needs; currently that is `httpx`.
- Hindsight recall must stay scoped with `tags_match: "all_strict"`.
- Retain should use item-level `tags` and async writes.
- Never send raw sender IDs, group IDs, or `unified_msg_origin` to Hindsight. Use the hashing helpers in `scope.py`.
- Recall injection should remain temporary via `TextPart(...).mark_as_temp()` and should not modify persistent AstrBot conversation history.
- Hindsight API failures should be logged and should not interrupt AstrBot replies.

## Testing Expectations

When changing behavior, update or add focused unit tests for:

- scope generation and hash isolation,
- recall result formatting,
- Hindsight client request bodies and error handling,
- plugin behavior around disabled scopes or incomplete config when practical.

Avoid committing generated files such as `__pycache__/`.
