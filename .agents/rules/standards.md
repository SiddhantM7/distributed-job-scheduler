\# Coding Standards



\* Python: follow PEP 8.

\* Use type hints on every function.

\* Add docstrings to all public functions and classes.

\* Never hardcode secrets. Read configuration and secrets from environment variables using `pydantic-settings`.

\* Every new API endpoint must have a corresponding pytest test.

\* Prefer explicit SQL using SQLAlchemy Core or raw SQL for the job-claim query. Do not use ORM abstractions that could hide or obscure the `FOR UPDATE SKIP LOCKED` behavior.

\* Follow `docs/database-design.md` for database-related implementation and design decisions.

\* Follow `docs/api-spec.md` for API-related implementation and endpoint behavior.

\* Before making architectural changes, check the existing project documentation and preserve established design decisions unless there is a strong reason to change them.



