"""Email attachments: extracted from raw MIME, filtered to real documents, and
carried on EmailMessage so the orchestration layer can ingest + link them."""

from __future__ import annotations

import email
from email import policy
from email.message import EmailMessage as PyEmailMessage

from pipeline.adapters.gmail import _extract_attachments, _parse_message, messages_from_thread


def _att(filename, maintype, subtype, data, disposition=None):
    return (filename, maintype, subtype, data, disposition)


def _build(body="Hello.", attachments=()):
    msg = PyEmailMessage()
    msg["From"] = "Ana <ana@x.com>"
    msg["To"] = "me@acme.com"
    msg["Subject"] = "Deck"
    msg["Date"] = "Mon, 1 Jun 2026 10:00:00 +0000"
    msg["Message-ID"] = "<a@x.com>"
    msg.set_content(body)
    for (filename, maintype, subtype, data, disposition) in attachments:
        kw = {}
        if filename:
            kw["filename"] = filename
        if disposition:
            kw["disposition"] = disposition
        msg.add_attachment(data, maintype=maintype, subtype=subtype, **kw)
    return msg.as_bytes()


def test_extract_attachments_keeps_documents_drops_inline_calendar_images_sigs():
    raw = _build(attachments=[
        _att("deck.pdf", "application", "pdf", b"%PDF-1.4 fake"),
        _att("logo.png", "image", "png", b"\x89PNG fake", "inline"),
        _att("photo.jpg", "image", "jpeg", b"\xff\xd8 fake"),
        _att("invite.ics", "text", "calendar", b"BEGIN:VCALENDAR"),
        _att("smime.p7s", "application", "pkcs7-signature", b"sig"),
    ])
    msg = email.message_from_bytes(raw, policy=policy.default)
    atts = _extract_attachments(msg)
    assert [a.filename for a in atts] == ["deck.pdf"]
    assert atts[0].content_type == "application/pdf"
    assert atts[0].data.startswith(b"%PDF")


def test_messages_from_thread_carries_attachments():
    parsed = _parse_message(_build(attachments=[
        _att("notes.txt", "text", "plain", b"Deal terms inside."),
    ]))
    msgs = messages_from_thread([parsed], tenant_id="T1", mailbox="me@acme.com").messages
    assert len(msgs) == 1
    assert [a.filename for a in msgs[0].attachments] == ["notes.txt"]
    assert msgs[0].attachments[0].data == b"Deal terms inside."


def test_message_without_attachments_has_empty_list():
    parsed = _parse_message(_build())
    msgs = messages_from_thread([parsed], tenant_id="T1", mailbox="me@acme.com").messages
    assert msgs[0].attachments == []
