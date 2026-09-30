"""First issuance stores final PDF bytes; repeated exports never re-render them."""
from hashlib import sha256
from secrets import token_urlsafe

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import ExportArtifact, now_utc


def issued_pdf(session, document, render):
    query = select(ExportArtifact).where(ExportArtifact.document_id == document.id,
                                       ExportArtifact.document_version == document.version)
    existing = session.scalar(query)
    if existing is not None:
        return existing.pdf_bytes
    public_id = token_urlsafe(24)
    content = render(public_id)
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    # One atomic unique-key winner. Losers read its exact bytes after commit.
    session.execute(insert(ExportArtifact).values(public_id=public_id, document_id=document.id,
        document_version=document.version, issued_at=now_utc(), sha256=sha256(content).hexdigest(),
        pdf_bytes=content).on_conflict_do_nothing(index_elements=["document_id", "document_version"]))
    session.commit()
    session.expire_all()
    return session.scalar(query).pdf_bytes
