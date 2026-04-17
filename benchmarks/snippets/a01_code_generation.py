# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A01 — Code Generation snippets (good / medium / bad).

Domain: Writing new REST API endpoints, service classes, CLI tools from scratch.
"""

GOOD: dict = {
    "eval_score": 9.2,
    "output": "Created /users/register endpoint with validation, hashing, and JWT response.",
    "code": '''\
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from datetime import datetime, UTC
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    created_at: datetime


async def register_user(
    payload: RegisterRequest,
    db: AsyncSession,
) -> RegisterResponse:
    """Register a new user with email validation and password hashing.

    Args:
        payload: Validated registration data.
        db: Database session (injected).

    Returns:
        RegisterResponse with the created user details.

    Raises:
        HTTPException 409: If email already exists.
    """
    existing = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    hashed = pwd_context.hash(payload.password)
    user = User(
        email=payload.email,
        password_hash=hashed,
        display_name=payload.display_name,
        created_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("User registered: %s", user.email)
    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        created_at=user.created_at,
    )
''',
}

MEDIUM: dict = {
    "eval_score": 5.8,
    "output": "Register endpoint created.",
    "code": """\
from fastapi import APIRouter
from pydantic import BaseModel
import hashlib

router = APIRouter()

class RegisterReq(BaseModel):
    email: str
    password: str

@router.post("/register")
async def register(req: RegisterReq, db):
    hashed = hashlib.sha256(req.password.encode()).hexdigest()
    user = {"email": req.email, "password": hashed}
    db.insert(user)
    return {"status": "ok", "email": req.email}
""",
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "error: incomplete",
    "code": """\
from fastapi import APIRouter

router = APIRouter()

@router.post("/register")
def register(data):
    # TODO: add validation
    user = {"email": data["email"], "pass": data["password"]}
    # save to db somehow
    return user
""",
}
