"""Load markdown runbooks and attach them to incidents by alert type."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from rootfold.events import add_event
from rootfold.models import Circuit, Incident

FRONT_MATTER = "---"


@dataclass
class Runbook:
    id: str
    title: str
    summary: str
    checks: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    body: str = ""
    path: str = ""

    def as_dict(self, *, score: int | None = None, primary: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "checks": list(self.checks),
            "body": self.body,
        }
        if score is not None:
            data["score"] = score
            data["primary"] = primary
        return data


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def runbook_dirs() -> list[Path]:
    root = _repo_root()
    return [root / "docs" / "runbooks", Path(__file__).resolve().parent / "runbooks"]


def _parse(path: Path) -> Runbook:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text
    if text.startswith(FRONT_MATTER):
        parts = text.split(FRONT_MATTER, 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
    match = meta.get("match") or {}
    return Runbook(
        id=str(meta.get("id") or path.stem),
        title=str(meta.get("title") or path.stem),
        summary=str(meta.get("summary") or ""),
        checks=[str(c).strip() for c in (meta.get("checks") or []) if str(c).strip()],
        names=[str(n).lower() for n in (match.get("names") or [])],
        keywords=[str(k).lower() for k in (match.get("keywords") or [])],
        media=[str(m).lower() for m in (match.get("media") or [])],
        body=body,
        path=str(path),
    )


def load_runbooks(*, force: bool = False) -> list[Runbook]:
    books: dict[str, Runbook] = {}
    for folder in runbook_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            book = _parse(path)
            books[book.id] = book
    return list(books.values())


def get_runbook(runbook_id: str) -> Runbook | None:
    for book in load_runbooks():
        if book.id == runbook_id:
            return book
    return None


def _haystack(inc: Incident, db: Session) -> tuple[str, str | None]:
    bits = [inc.title or "", inc.kind or ""]
    for alert in inc.alerts or []:
        bits.append(alert.name or "")
        bits.append(alert.summary or "")
        if alert.labels:
            bits.extend(str(v) for v in alert.labels.values())
    media = None
    if inc.root_type == "circuit" and inc.root_id is not None:
        circuit = db.get(Circuit, inc.root_id)
        if circuit is not None:
            media = (circuit.media or "").lower()
            bits.append(circuit.media or "")
            bits.append(circuit.name or "")
    return " ".join(bits).lower(), media


def score_runbook(book: Runbook, inc: Incident, db: Session) -> int:
    text, media = _haystack(inc, db)
    score = 0
    for name in book.names:
        if name and name in text:
            score += 10
    for word in book.keywords:
        if word and word in text:
            score += 3
    if media and media in book.media:
        score += 4
    return score


def attach_runbooks(db: Session, inc: Incident) -> list[dict[str, Any]]:
    scored = []
    for book in load_runbooks():
        points = score_runbook(book, inc, db)
        if points > 0:
            scored.append((points, book))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    out = []
    for index, (points, book) in enumerate(scored):
        out.append(book.as_dict(score=points, primary=index == 0))
    return out


def add_checks(
    db: Session,
    inc: Incident,
    checks: list[str],
    *,
    actor: str,
    now,
) -> Incident:
    current = [str(c).strip() for c in (inc.checks or []) if str(c).strip()]
    added = []
    for check in checks:
        item = str(check).strip()
        if item and item not in current:
            current.append(item)
            added.append(item)
    inc.checks = current
    if added:
        add_event(
            db,
            inc.id,
            at=now,
            actor=actor,
            kind="check",
            message=f"{actor} ticked {len(added)} runbook check(s)",
            data={"added": added},
        )
    db.flush()
    return inc


def library() -> list[dict[str, Any]]:
    return [book.as_dict() for book in load_runbooks()]
