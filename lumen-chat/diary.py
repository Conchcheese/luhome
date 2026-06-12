"""
AI 日记：保存总结后的私密日记，并按模型决定可选发布朋友圈。
"""

import asyncio
import json
import time
from typing import Any, Optional

from database import get_db
from ws import manager


def parse_diary_payload(raw: str) -> Optional[dict[str, Any]]:
    """从模型输出中提取日记 JSON。"""
    if not raw:
        return None
    text = raw.strip()
    if "```" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def normalize_diary_payload(data: dict[str, Any]) -> tuple[dict[str, str], Optional[dict[str, Any]]]:
    """兼容轻微格式漂移，输出日记字段和可选朋友圈字段。"""
    diary_raw = data.get("diary", {})
    if isinstance(diary_raw, str):
        diary = {"title": "", "content": diary_raw, "mood": ""}
    elif isinstance(diary_raw, dict):
        diary = {
            "title": str(diary_raw.get("title") or "").strip(),
            "content": str(diary_raw.get("content") or "").strip(),
            "mood": str(diary_raw.get("mood") or "").strip(),
        }
    else:
        diary = {"title": "", "content": "", "mood": ""}

    moment = None
    if bool(data.get("post_moment")):
        moment_raw = data.get("moment", {})
        if isinstance(moment_raw, str):
            moment = {"content": moment_raw.strip(), "expect_reply": False}
        elif isinstance(moment_raw, dict):
            moment = {
                "content": str(moment_raw.get("content") or "").strip(),
                "expect_reply": bool(moment_raw.get("expect_reply", False)),
            }

    return diary, moment


async def save_diary_entry(
    *,
    author: str,
    title: str,
    content: str,
    mood: str = "",
    source_type: str = "",
    source_ref: str = "",
    source_start_ts: float | None = None,
    source_end_ts: float | None = None,
) -> Optional[dict[str, Any]]:
    """保存一篇 AI 日记，并广播给打开的日记本页面。"""
    content = (content or "").strip()
    if not content:
        return None
    now = time.time()
    entry_id = f"di_{author}_{int(now * 1000)}"
    entry = {
        "id": entry_id,
        "author": author,
        "title": (title or "").strip(),
        "content": content,
        "mood": (mood or "").strip(),
        "source_type": source_type or "",
        "source_ref": source_ref or "",
        "source_start_ts": source_start_ts,
        "source_end_ts": source_end_ts,
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


async def publish_ai_moment(
    *,
    author: str,
    content: str,
    expect_reply: bool = False,
    source_conv: str | None = None,
    source_msg_id: str | None = None,
) -> Optional[dict[str, Any]]:
    """复用现有朋友圈数据结构发布 AI 朋友圈。"""
    content = (content or "").strip()
    if not content:
        return None
    now = time.time()
    moment_id = f"mt_{int(now * 1000)}"
    expect = 1 if expect_reply else 0
    async with get_db() as db:
        await db.execute(
            "INSERT INTO moments (id, author, content, source_conv, source_msg_id, expect_reply, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (moment_id, author, content, source_conv, source_msg_id, expect, now),
        )
        await db.commit()
    moment_data = {
        "id": moment_id,
        "author": author,
        "content": content,
        "source_conv": source_conv,
        "source_msg_id": source_msg_id,
        "expect_reply": expect,
        "created_at": now,
        "comments": [],
        "reactions": [],
    }
    await manager.broadcast({"type": "moment_new", "data": moment_data})
    if expect_reply:
        from routes.moments import _trigger_ai_replies
        asyncio.create_task(_trigger_ai_replies(moment_id, exclude_author=author))
    return moment_data
