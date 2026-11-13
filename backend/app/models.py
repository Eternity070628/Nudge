"""数据契约。前后端、Agent 之间只通过这些结构通信。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["competition", "scholarship", "lecture", "affairs", "exam", "activity", "other"]
Campus = Literal["haidian", "shahe", "hainan", "unknown"]


class Deadline(BaseModel):
    start: Optional[str] = None          # ISO8601
    end: Optional[str] = None
    raw: str = ""                         # 原文片段，必须保留
    confidence: float = 0.0


class Material(BaseModel):
    name: str
    required: bool = True
    note: str = ""


class Audience(BaseModel):
    grades: list[str] = Field(default_factory=list)
    majors: list[str] = Field(default_factory=list)
    colleges: list[str] = Field(default_factory=list)
    raw: str = ""


class Submission(BaseModel):
    channel: Literal["web", "email", "offline", "unknown"] = "unknown"
    url: str = ""
    email: str = ""
    location: str = ""
    campus: Campus = "unknown"


class Source(BaseModel):
    type: Literal["link", "image", "pdf", "text"] = "text"
    url: str = ""
    captured_at: str = ""


class EventDraft(BaseModel):
    """抽取 Agent 的输出，也是人工确认界面的展示结构。"""
    title: str = ""
    category: Category = "other"
    campus: Campus = "unknown"
    deadline: Deadline = Field(default_factory=Deadline)
    audience: Audience = Field(default_factory=Audience)
    materials: list[Material] = Field(default_factory=list)
    submission: Submission = Field(default_factory=Submission)
    evidence: dict[str, str] = Field(default_factory=dict)
    source: Source = Field(default_factory=Source)
    importance: int = 3
    confidence: dict[str, float] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    needs_review: list[str] = Field(default_factory=list)   # 低置信度字段
    warnings: list[str] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    text: str
    source_type: Literal["link", "image", "pdf", "text"] = "text"
    url: str = ""
    published_at: Optional[str] = None   # 通知发布时间，相对时间的锚点


class EventCreate(BaseModel):
    draft: EventDraft
    user_id: str = "u_demo"


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    nickname: str
    email: str
    password: str
    confirm: str
    code: str


class ResetRequest(BaseModel):
    email: str
    code: str
    password: str
    confirm: str


class SendCodeRequest(BaseModel):
    email: str
    purpose: Literal["register", "reset", "change_email_old", "change_email_new", "change_password"]


class SettingsCodeRequest(BaseModel):
    target: Literal["old", "new", "password"]
    new_email: str = ""


class EmailChangeRequest(BaseModel):
    old_code: str
    new_email: str
    new_code: str


class PasswordChangeRequest(BaseModel):
    method: Literal["old", "code"]
    old_password: str = ""
    code: str = ""
    password: str
    confirm: str
