## What changed?

Brief description of the changes.

## Why?

What problem does this solve or what feature does it add?

## Test results

```
python3 -m pytest tests/ -v
```

## Checklist

- [ ] Tests pass (`python3 -m pytest tests/ -v`)
- [ ] No new external dependencies (zero-dep rule)
- [ ] Follows existing patterns in `cli.py` / `fmt.py`
- [ ] Updated CHANGELOG.md (if user-facing change)
- [ ] New commands added to `cmd_help()` in `cli.py`
