"""Normalized internal schema for case-management data.

Defined *before* any adapter (plan.md Workstream C): every provider maps to
and from these five shapes. Adapters translate; nothing upstream ever sees a
provider-specific field.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Contact(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None


class Lead(BaseModel):
    contact: Contact
    source: str = "phone"
    practice_area: str | None = None
    status: str = "new"
    qualification: dict | None = None


class Matter(BaseModel):
    description: str
    practice_area: str | None = None
    status: str = "pending"


class Task(BaseModel):
    name: str
    due_at: datetime | None = None


class Note(BaseModel):
    subject: str
    detail: str
