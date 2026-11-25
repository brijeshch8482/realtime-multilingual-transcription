from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import Transcription
from ..schemas import (
    TranscriptionCreate,
    TranscriptionOut,
    TranscriptionPage,
    TranscriptionUpdate,
)
from ..langdetect import detect_languages
from ..textutil import default_title, detect_languages_by_script

router = APIRouter(prefix="/api/transcriptions", tags=["transcriptions"])


def _clean_codes(codes: list[str] | None) -> list[str]:
    out: list[str] = []
    for c in codes or []:
        c = c.strip().lower()
        if 2 <= len(c) <= 3 and c.isalpha() and c not in out:
            out.append(c)
    return out


def _refine_languages(item_id: str, text: str) -> None:
    """Background: replace the instant script-based tags with model-detected ones."""
    langs = detect_languages(text)
    with SessionLocal() as db:
        item = db.get(Transcription, item_id)
        if item is not None and item.text == text and item.languages != langs:
            item.languages = langs
            db.commit()


def _get_or_404(db: Session, item_id: str) -> Transcription:
    item = db.get(Transcription, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Transcription not found")
    return item


@router.get("", response_model=TranscriptionPage)
def list_transcriptions(
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(Transcription)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Transcription.title.ilike(like), Transcription.text.ilike(like))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Transcription.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return TranscriptionPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{item_id}", response_model=TranscriptionOut)
def get_transcription(item_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, item_id)


@router.post("", response_model=TranscriptionOut, status_code=status.HTTP_201_CREATED)
def create_transcription(
    body: TranscriptionCreate, background: BackgroundTasks, db: Session = Depends(get_db)
):
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be empty")
    item = Transcription(
        title=(body.title or "").strip() or default_title(text),
        text=text,
        languages=_clean_codes(body.languages) or detect_languages_by_script(text),
        duration_sec=body.duration_sec,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    if not _clean_codes(body.languages):
        background.add_task(_refine_languages, item.id, text)
    return item


@router.put("/{item_id}", response_model=TranscriptionOut)
def update_transcription(
    item_id: str,
    body: TranscriptionUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if body.title is not None:
        item.title = body.title.strip() or item.title
    if body.text is not None:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="Text cannot be empty")
        if text != item.text:
            item.text = text
            item.languages = detect_languages_by_script(text)
            background.add_task(_refine_languages, item.id, text)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transcription(item_id: str, db: Session = Depends(get_db)):
    item = _get_or_404(db, item_id)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
