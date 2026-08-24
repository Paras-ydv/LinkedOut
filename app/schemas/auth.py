"""Pydantic schemas for the auth/verification endpoints.

None of these carry plaintext PII back out of the API after the request
that supplied it — responses only ever echo back tier/token/status info.
"""

import uuid

from pydantic import BaseModel, Field

from app.models.enums import DocumentType, VerificationTier


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class OTPRequestIn(BaseModel):
    phone: str = Field(..., description="E.164 phone number, e.g. +15551234567")


class OTPRequestOut(BaseModel):
    message: str = "OTP sent"
    expires_in_seconds: int


class OTPVerifyIn(BaseModel):
    phone: str
    code: str


class OTPVerifyOut(TokenPair):
    user_id: uuid.UUID
    verification_tier: VerificationTier


class EmailRequestIn(BaseModel):
    email: str = Field(..., description="Corporate email to verify")


class EmailRequestOut(BaseModel):
    message: str = "verification code sent"
    expires_in_seconds: int


class EmailVerifyIn(BaseModel):
    email: str
    code: str


class EmailVerifyOut(TokenPair):
    user_id: uuid.UUID
    verification_tier: VerificationTier


class DocumentUploadOut(BaseModel):
    message: str = "document queued for review"
    moderation_id: uuid.UUID
    doc_type: DocumentType
    status: str
