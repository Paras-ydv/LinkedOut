"""Document verification abstraction (Tier 3).

Phase 1 only wires up the *interface* and a manual-review stub that queues
the upload for a human — no OCR/auto-verification logic yet. The stub is
also responsible for the ephemeral-storage contract: the plaintext file is
written to a short-lived temp path (never permanent disk/S3), and the
returned `ephemeral_path` is what a later admin-review endpoint (Phase 4)
deletes immediately on approval/rejection via `delete_ephemeral_file`.
"""

import contextlib
import hashlib
import os
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.enums import DocumentType


@dataclass(frozen=True)
class QueuedDocument:
    content_hash: str
    ephemeral_path: str


class DocumentVerificationProvider(ABC):
    @abstractmethod
    async def submit(
        self, user_id: uuid.UUID, doc_type: DocumentType, content: bytes
    ) -> QueuedDocument:
        """Accept a document's raw bytes for verification.

        Implementations must not write `content` to permanent storage.
        Returns the info needed to create a `ModerationQueueItem` row.
        """
        raise NotImplementedError


class ManualReviewDocumentProvider(DocumentVerificationProvider):
    """Writes the file to an ephemeral temp path and queues it for manual review.

    No OCR/auto-verification — approval/rejection happens via a human
    reviewer through a separate admin endpoint added in Phase 4.
    """

    async def submit(
        self, user_id: uuid.UUID, doc_type: DocumentType, content: bytes
    ) -> QueuedDocument:
        content_hash = hashlib.sha256(content).hexdigest()

        # NamedTemporaryFile(delete=False) so the path survives past this
        # call for the reviewer to read; `delete_ephemeral_file` below is
        # the only intended way it gets cleaned up.
        fd, path = tempfile.mkstemp(prefix=f"docverify_{user_id}_", suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
        except BaseException:
            delete_ephemeral_file(path)
            raise

        return QueuedDocument(content_hash=content_hash, ephemeral_path=path)


def delete_ephemeral_file(path: str) -> None:
    """Best-effort delete of an ephemeral document temp file."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
