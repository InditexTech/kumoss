# Scheduler — Estado de implementación

## Issue de referencia
GitHub Issue #86: Terraform operations scheduler — durable Postgres-backed queue, deferred & recurring runs.

## Qué es
Un scheduler durable respaldado por Postgres que reemplaza `BackgroundTasks` de FastAPI para todas las operaciones Terraform. Las operaciones se guardan como filas en la DB, se reclaman con `FOR UPDATE SKIP LOCKED`, se rastrean de principio a fin, y opcionalmente se pueden diferir o programar con cron.

## Estado actual: solo DRIFT habilitado
El código está completo pero **solo acepta operaciones DRIFT**. Las demás (GENERATE, APPLY, IMPORT) están bloqueadas con error 501 en `queue_service.py:enqueue()` y `executor.py:_build_handler()`. Para activar otra operación: añadir al `_ENABLED_KINDS` frozenset en `queue_service.py` y añadir el `case` correspondiente en `executor.py:_build_handler()`.

---

## Lo que está hecho (Fases 1-5)

### Archivos del scheduler
```
core/src/scheduler/
├── __init__.py           — Paquete
├── constants.py          — OperationKind (GENERATE/DRIFT/APPLY/IMPORT), OperationStatus (PENDING/RUNNING/SUCCEEDED/FAILED/CANCELLED)
├── config.py             — SchedulerConfig (Pydantic): concurrency, intervalos, leases, retry, timeouts
├── models.py             — Operation + OperationSchedule (SQLAlchemy, heredan de Base → create_all las crea)
├── queue_service.py      — OperationQueueService: enqueue, claim (FOR UPDATE SKIP LOCKED), heartbeat, complete, fail, cancel, reap_expired_leases, list/get
├── executor.py           — OperationExecutor: execute(op) — refactor de _make_runner de terraform.py. Acquire → tracer → clone → handler → complete. Solo DRIFT activo.
├── scheduler.py          — OperationScheduler: claim loops (×concurrency), reaper loop (×1), cron materializer (×1). start()/stop() para lifespan.
└── api/
    ├── __init__.py
    ├── dtos.py            — Pydantic request/response: OperationResponse, ScheduleResponse, Create/Update requests, paginación
    └── router.py          — operations_router (GET list, GET detail, POST cancel) + schedules_router (POST, GET, PATCH, DELETE)
```

### Tests
```
core/tests/scheduler/
├── __init__.py
└── test_queue_service.py  — Tests contra Postgres real: enqueue, claim, heartbeat, complete, fail (terminal + retry), cancel (pending/running/terminal), reaper (requeue + fail at max_attempts), claim concurrente (SKIP LOCKED), scheduled_at futuro
```

### Archivos existentes modificados
- `core/src/shared/config/system_config.py` — añadido import de `SchedulerConfig` + campo `scheduler: SchedulerConfig` en `SystemConfig`
- `config.yaml` — añadido bloque `scheduler:` al final con defaults documentados

---

## Lo que falta (Fase 6): Integración

**No se ha tocado ningún archivo existente de lógica.** La integración requiere 3 cambios:

### 1. `core/src/main.py`
- Importar y registrar los routers: `operations_router` y `schedules_router` de `src.scheduler.api.router`
- En `lifespan` startup (tras `configure_git_credentials`): instanciar `OperationQueueService`, `OperationExecutor`, `OperationScheduler`, llamar `await scheduler.start()`, guardar en `app.state`
- En `lifespan` shutdown (antes de cerrar redis/db): `await app.state.scheduler.stop()`
- Añadir tags metadata para "Operations" y "Schedules"

### 2. `core/src/api/v1/terraform.py`
- Eliminar import de `BackgroundTasks` y la función `_make_runner` completa (líneas 63-117)
- Cada endpoint: reemplazar `background_tasks.add_task(_make_runner(ctx, build))` por `await queue_service.enqueue(session_uuid, kind, params)`
- Response cambia de `{"session_id"}` a `{"session_id", "operation_id"}` (aditivo)
- Apply: mantener check `is_session_blocked` antes de enqueue
- **Nota:** como solo DRIFT está activo, solo el endpoint de drift usaría el scheduler inicialmente. Generate y apply pueden seguir con BackgroundTasks hasta activarlos.

### 3. `core/pyproject.toml`
- Añadir `croniter>=5.0.0` a las dependencias

---

## Código existente que se reutiliza (no tocar)

| Archivo | Qué se usa |
|---|---|
| `core/src/domains/services/database_service.py` | `acquire_in_flight`, `release_in_flight`, `mark_completed`, `mark_failed`, `get_last_status`, `is_session_blocked`, `get_session_context`, `create_session` — todos `@staticmethod`, reciben session UUID |
| `core/src/application/factory.py` | `ApplicationFactory(ctx).get_terraform_drift_handler()` — dispatch de handlers |
| `core/src/application/services/session_orchestration_service.py` | `resolve()` en endpoints (no cambia) |
| `core/src/infrastructure/filesystem/workspace.py` | `WorkspaceService`: `setup_call_dir`, `cleanup` |
| `core/src/infrastructure/telemetry/phoenix/phoenix_tracer.py` | `PhoenixTracer` — tracing |
| `core/src/infrastructure/external/notification_service.py` | `NotificationServiceClient.notify_exception_failure` |
| `core/src/infrastructure/database/session.py` | `SessionManager` — sesiones async SQLAlchemy |
| `core/src/infrastructure/database/database.py` | `db` singleton — `create`, `get_by`, `query`, `transaction()` |

---

## Conceptos clave para entender el código

### Claim con FOR UPDATE SKIP LOCKED
El `claim()` en `queue_service.py` usa SQL raw porque el patrón subquery + `FOR UPDATE SKIP LOCKED` + `RETURNING *` no es expresable vía el ORM. Múltiples workers ejecutan claim al mismo tiempo; SKIP LOCKED hace que cada uno salte filas bloqueadas y coja la siguiente, sin esperas.

### Leases y crash recovery
Cada operación RUNNING tiene un `lease_expires_at`. El executor lo extiende cada `heartbeat_interval` (30s). Si un worker muere, deja de extender el lease. El reaper (loop cada 60s) detecta leases expirados, reencola la op, y **libera `in_flight` de la sesión** — el fix del bug de sesiones bloqueadas para siempre.

### Separación scheduler vs core
El scheduler tiene sus propios enums (`OperationKind` vs `OperationType` del core) y sus propios modelos. No toca los enums ni modelos existentes. Los únicos puntos de contacto son: heredar de `Base` (para que `create_all` cree las tablas) y llamar a métodos de `DatabaseService` (que reciben session UUID).

### Solo DRIFT por ahora
- `queue_service.py` línea ~50: `_ENABLED_KINDS = frozenset({OperationKind.DRIFT})`
- `executor.py:_build_handler()`: solo tiene `case OperationKind.DRIFT`, el `case _` devuelve 501

---

## Para probar

Los tests requieren Postgres + Redis corriendo. Con el stack Docker:
```bash
docker compose up core-db redis -d
# Ajustar NEBULA_SQL_DATABASE_URL en core/.env a localhost si es necesario
cd core
pytest tests/scheduler/test_queue_service.py -v
```

---

## Otros documentos relacionados
- `ISSUE_86_PLAN.md` (raíz del repo) — análisis de coste y desglose por fases
- `/Users/nicolaspl/.claude/plans/sleepy-frolicking-elephant.md` — plan detallado de implementación con decisiones técnicas
