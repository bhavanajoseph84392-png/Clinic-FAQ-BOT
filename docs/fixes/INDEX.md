# Fixes Index

Final suite: `python -m pytest -q` -> 53 passed, 0 failed, 0 skipped.

| Issue | Status | Commit hash | Tests added | Open questions |
| --- | --- | --- | --- | --- |
| H-03 | DONE | `15f5f77` | `tests/test_worker_resilience.py` | None |
| H-08 | DONE | `5e717fd` | `tests/test_admin_api_session.py` | None |
| H-04 | DONE | `ccfe247` | `tests/test_migrate_script.py` | None; checksums intentionally not covered |
| C-09 | DONE | `fec3487` | `tests/test_seed_demo_safety.py` | None; audit note about a migrate host guard did not match current code |
| H-14 | DONE | `b79aab8` | `tests/test_email_html_escaping.py` | None |
| H-15 | DONE | `ac2fe35` | `tests/test_email_validation.py` | None |
| H-18 | DONE | `40c0bc7` | `tests/test_cookie_security.py` | None; revocation and lifetime intentionally not covered |
