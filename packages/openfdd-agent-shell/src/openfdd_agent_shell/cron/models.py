from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ScheduleKind = Literal["at", "every", "cron"]
SessionStyle = Literal["worker", "isolated", "main", "session"]
ServiceKind = Literal[
    "noop",
    "shell",
    "memory_append",
    "codex_turn",
    "fdd_batch",
    "health_bridge",
    "health_hvac",
    "webhook",
]


@dataclass
class Schedule:
    kind: ScheduleKind
    at_iso: str | None = None
    every_seconds: int | None = None
    cron_expr: str | None = None
    timezone: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.at_iso is not None:
            data["at_iso"] = self.at_iso
        if self.every_seconds is not None:
            data["every_seconds"] = self.every_seconds
        if self.cron_expr is not None:
            data["cron_expr"] = self.cron_expr
        if self.timezone is not None:
            data["timezone"] = self.timezone
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Schedule:
        kind = str(raw.get("kind") or "every")
        if kind not in {"at", "every", "cron"}:
            raise ValueError(f"unsupported schedule kind: {kind}")
        every_seconds = raw.get("every_seconds")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            at_iso=raw.get("at_iso"),
            every_seconds=int(every_seconds) if every_seconds is not None else None,
            cron_expr=raw.get("cron_expr"),
            timezone=raw.get("timezone"),
        )


@dataclass
class CronJob:
    id: str
    name: str
    schedule: Schedule
    service: ServiceKind
    session: SessionStyle = "worker"
    enabled: bool = True
    delete_after_run: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "schedule": self.schedule.to_dict(),
            "service": self.service,
            "session": self.session,
            "enabled": self.enabled,
            "delete_after_run": self.delete_after_run,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CronJob:
        service = str(raw.get("service") or "noop")
        session = str(raw.get("session") or "worker")
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw["id"]),
            schedule=Schedule.from_dict(raw.get("schedule") or {}),
            service=service,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
            enabled=bool(raw.get("enabled", True)),
            delete_after_run=bool(raw.get("delete_after_run", False)),
            payload=dict(raw.get("payload") or {}),
        )


@dataclass
class CronRunResult:
    job_id: str
    run_id: str
    status: Literal["ok", "error", "skipped"]
    message: str
    started_at: str
    finished_at: str
