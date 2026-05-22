"""
日记本 API：列表查询、新增、编辑、删除。
"""

import time
import aiosqlite
from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_db
from ws import manager

router = APIRouter(prefix="/api/diaries", tags=["diaries"])


class DiaryCreate(BaseModel):
    title: str = ""
    content: str
    mood: str = ""


class DiaryUpdate(BaseModel):
    title: str = ""
    content: str
    mood: str = ""


@router.get("")
async def list_diaries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    author: str = Query("", max_length=32),
):
    """分页获取日记，author 可选：user / aion / connor。"""
    offset = (page - 1) * page_size
    where = ""
    params: list[object] = []
    if author:
        where = "WHERE author=?"
        params.append(author)

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(f"SELECT COUNT(*) as cnt FROM diary_entries {where}", params)
        total = (await cur.fetchone())["cnt"]
        cur = await db.execute(
            "SELECT id, author, title, content, mood, source_type, source_ref, "
            "source_start_ts, source_end_ts, created_at "
            f"FROM diary_entries {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        )
        rows = await cur.fetchall()

    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.post("")
async def create_diary(body: DiaryCreate):
    """用户手动新增一篇日记。"""
    content = body.content.strip()
    if not content:
        return {"error": "内容不能为空"}
    now = time.time()
    entry_id = f"di_user_{int(now * 1000)}"
    entry = {
        "id": entry_id,
        "author": "user",
        "title": body.title.strip(),
        "content": content,
        "mood": body.mood.strip(),
        "source_type": "manual",
        "source_ref": "",
        "source_start_ts": None,
        "source_end_ts": None,
        "created_at": now,
    }
    async with get_db() as db:
        await db.execute(
            "INSERT INTO diary_entries "
            "(id, author, title, content, mood, source_type, source_ref, source_start_ts, source_end_ts, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                entry["id"], entry["author"], entry["title"], entry["content"],
                entry["mood"], entry["source_type"], entry["source_ref"],
                entry["source_start_ts"], entry["source_end_ts"], entry["created_at"],
            ),
        )
        await db.commit()
    await manager.broadcast({"type": "diary_new", "data": entry})
    return entry


@router.put("/{entry_id}")
async def update_diary(entry_id: str, body: DiaryUpdate):
    """编辑一篇日记的标题、正文和心情。"""
    content = body.content.strip()
    if not content:
        return {"error": "内容不能为空"}
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE diary_entries SET title=?, content=?, mood=? WHERE id=?",
            (body.title.strip(), content, body.mood.strip(), entry_id),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT id, author, title, content, mood, source_type, source_ref, "
            "source_start_ts, source_end_ts, created_at FROM diary_entries WHERE id=?",
            (entry_id,),
        )
        row = await cur.fetchone()
    if not row:
        return {"error": "日记不存在"}
    entry = dict(row)
    await manager.broadcast({"type": "diary_updated", "data": entry})
    return entry


@router.delete("/{entry_id}")
async def delete_diary(entry_id: str):
    """删除一篇日记。"""
    async with get_db() as db:
        await db.execute("DELETE FROM diary_entries WHERE id=?", (entry_id,))
        await db.commit()
    return {"ok": True}
