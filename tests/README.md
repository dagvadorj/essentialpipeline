# Tests

```
pytest                    # the default suite - fast, no external services needed
pytest -m docker          # also run real-Docker execution tests (needs a reachable daemon; auto-skipped otherwise)
pytest -m network         # also run the real Safety vulnerability-database lookup (needs network access)
pytest -m "docker or network"   # everything
```

## How this is set up

- **Database**: a single in-memory SQLite database for the whole run (`TestingConfig`), created once and wiped after each test (`_clean_db` in `conftest.py`) rather than per-test transaction rollback - several code paths under test call `db.session.commit()` internally (`execute_task`, `queue_task_execution`), which doesn't play well with a rollback-based approach.
- **Docker**: mocked everywhere except `test_docker_integration.py` (marked `@pytest.mark.docker`, skipped automatically if no daemon is reachable) - that file is the one place the real container lifecycle (`utils/docker.py`) gets exercised end to end, since that's exactly where several real bugs were found and fixed (see `plan.md`).
- **Safety**: its vulnerability-database lookup needs network access. The blocking/non-blocking scan-status logic is tested with a mocked response (`test_security_scan.py`); one real end-to-end check is marked `@pytest.mark.network`.
- **Fixtures** (`conftest.py`): `client`, `test_user`/`other_user`/`admin_user` (+ matching `*_headers` for auth), `make_zip`, and `make_project_version` (creates a real `Project`/`ProjectVersion`/`ProjectFile` backed by an actual zip on disk, so `extract_project_archive()` and the security scanner operate on it exactly as they would for a real upload).

## A structural gotcha worth knowing before adding more tests

`get_config()` (`essentialpipeline/config/__init__.py`), used internally by `services/scheduler.py`, ignores `create_app()`'s `config_env` argument and reads `FLASK_ENV` from the OS environment instead. `conftest.py` sets `FLASK_ENV=testing` at import time to work around this - if that line is ever removed, scheduler internals will silently fall back to `DevelopmentConfig`. This is a real bug in the application, not just a test-harness quirk; it just hasn't been fixed at the source yet (out of scope for the pass that added this suite).
