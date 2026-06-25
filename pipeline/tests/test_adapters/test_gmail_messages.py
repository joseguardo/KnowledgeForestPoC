"""Step-1 email extraction: one thread → one record per message.

`messages_from_thread` turns the parsed RFC822 messages of a thread into
per-message records (the new atomic unit), each keyed by its Message-ID and
tagged with a shared thread_id for grouping. Direction and entity classification
are applied later (they need run context), so this layer stays pure.
"""

import base64
from email.message import EmailMessage as _PyEmailMessage

from pipeline.adapters.gmail import (
    EmailMessage,
    _parse_message,
    messages_from_thread,
)

from .test_gmail import _raw


def _parse(*raws: str) -> list[dict]:
    return [_parse_message(base64.urlsafe_b64decode(r)) for r in raws]


def _flatten(*raws: str):
    return messages_from_thread(_parse(*raws), tenant_id="T1", mailbox="me@acme.com").messages


def _reject(*raws: str):
    return messages_from_thread(_parse(*raws), tenant_id="T1", mailbox="me@acme.com").rejections


_HUMAN = dict(
    sender="Alice <alice@x.com>", to="me@acme.com", subject="Deal",
    date="Mon, 1 Jun 2026 10:00:00 +0000", body="Body.", msgid="<root@x.com>",
)


def _human(**over) -> str:
    return _raw(**{**_HUMAN, **over})


def test_thread_yields_one_record_per_message():
    parsed = _parse(
        _raw("Alice <alice@x.com>", "me@acme.com", "Deal", "Mon, 1 Jun 2026 10:00:00 +0000",
             "First.", "<root@x.com>"),
        _raw("me@acme.com", "Alice <alice@x.com>", "Re: Deal", "Mon, 1 Jun 2026 12:00:00 +0000",
             "Reply.", "<r2@acme.com>", references="<root@x.com>", cc="Bob <bob@y.com>"),
    )
    msgs = messages_from_thread(parsed, tenant_id="T1", mailbox="me@acme.com").messages

    assert len(msgs) == 2
    assert all(isinstance(m, EmailMessage) for m in msgs)
    # Each message keeps its own identity…
    assert [m.message_id for m in msgs] == ["<root@x.com>", "<r2@acme.com>"]
    # …but shares one thread_id for grouping.
    assert msgs[0].thread_id == msgs[1].thread_id
    assert msgs[0].tenant_id == "T1" and msgs[0].mailbox == "me@acme.com"


def test_record_captures_sender_and_recipients():
    parsed = _parse(
        _raw("me@acme.com", "Alice <alice@x.com>", "Re: Deal", "Mon, 1 Jun 2026 12:00:00 +0000",
             "Reply.", "<r2@acme.com>", cc="Bob <bob@y.com>"),
    )
    m = messages_from_thread(parsed, tenant_id="T1", mailbox="me@acme.com").messages[0]
    assert m.sender == ("me@acme.com", None)
    assert m.to == [("alice@x.com", "Alice")]
    assert m.cc == [("bob@y.com", "Bob")]
    assert "12:00:00" in m.occurred_at


def test_addresses_are_lowercased():
    parsed = _parse(
        _raw("Alice <Alice@X.com>", "ME@Acme.com", "Hi", "Mon, 1 Jun 2026 10:00:00 +0000",
             "Body.", "<root@x.com>"),
    )
    m = messages_from_thread(parsed, tenant_id="T1", mailbox="me@acme.com").messages[0]
    assert m.sender == ("alice@x.com", "Alice")
    assert m.to == [("me@acme.com", None)]


def test_missing_message_id_gets_stable_fallback():
    raw = _raw("Alice <alice@x.com>", "me@acme.com", "Hi", "Mon, 1 Jun 2026 10:00:00 +0000",
               "Body.", "")  # empty Message-ID
    p1 = _parse(raw)
    p2 = _parse(raw)
    id1 = messages_from_thread(p1, tenant_id="T1", mailbox="me@acme.com").messages[0].message_id
    id2 = messages_from_thread(p2, tenant_id="T1", mailbox="me@acme.com").messages[0].message_id
    assert id1 and id1 == id2  # deterministic, non-empty


# ── non-human mail is dropped (newsletters / automated / no-reply) ──


def test_newsletter_with_list_unsubscribe_is_dropped():
    assert _flatten(_human(extra_headers={"List-Unsubscribe": "<mailto:u@x.com>"})) == []


def test_list_id_is_dropped():
    assert _flatten(_human(extra_headers={"List-Id": "<news.x.com>"})) == []


def test_precedence_bulk_is_dropped():
    assert _flatten(_human(extra_headers={"Precedence": "bulk"})) == []


def test_auto_submitted_is_dropped():
    assert _flatten(_human(extra_headers={"Auto-Submitted": "auto-generated"})) == []


def test_no_reply_sender_is_dropped():
    assert _flatten(_human(sender="Acme <no-reply@acme.com>")) == []


def test_plain_human_message_is_kept():
    assert len(_flatten(_human())) == 1


def test_noreply_anywhere_in_localpart_is_dropped():
    # 'comments-noreply@docs.google.com' — noreply not at the start of the local part
    assert _flatten(_human(sender="Docs <comments-noreply@docs.google.com>")) == []


def test_brand_team_display_name_is_dropped():
    # marketing email with no bulk headers, but a brand/team display name
    assert _flatten(_human(sender="El equipo de Miro <your@product.miro.com>")) == []


def test_single_token_brandy_display_name_is_dropped():
    assert _flatten(_human(sender="Fun.xyz <fun@swapped.com>")) == []


def test_role_mailbox_sender_is_dropped():
    for lp in ("info", "sales", "marketing", "newsletter"):
        assert _flatten(_human(sender=f"South Summit <{lp}@southsummit.io>")) == [], lp


def test_role_mailbox_recipient_does_not_drop_human_message():
    # a role mailbox as a recipient must not drop a genuine human-sent message
    assert len(_flatten(_human(to="info@acme.com"))) == 1


def test_real_single_name_is_kept():
    assert len(_flatten(_human(sender="Matthias <matthias@firm.com>"))) == 1


def test_initials_display_name_is_kept():
    assert len(_flatten(_human(sender="J.P. <jp@firm.com>"))) == 1


def test_meeting_invite_is_dropped():
    """A calendar invite (text/calendar part) is dropped — handled by the
    separate calendar path, not the email graph."""
    msg = _PyEmailMessage()
    msg["From"] = "Alice <alice@x.com>"
    msg["To"] = "me@acme.com"
    msg["Subject"] = "Invite: Sync"
    msg["Date"] = "Mon, 1 Jun 2026 10:00:00 +0000"
    msg["Message-ID"] = "<inv@x.com>"
    msg.set_content("You are invited.")
    msg.add_alternative("BEGIN:VCALENDAR\nEND:VCALENDAR\n", subtype="calendar")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    assert _flatten(raw) == []


def test_subject_and_body_are_retained_for_later_steps():
    parsed = _parse(
        _raw("Alice <alice@x.com>", "me@acme.com", "Q3 secret terms",
             "Mon, 1 Jun 2026 10:00:00 +0000", "The body.", "<root@x.com>"),
    )
    m = messages_from_thread(parsed, tenant_id="T1", mailbox="me@acme.com").messages[0]
    assert m.subject == "Q3 secret terms"
    assert "the body" in m.body.lower()


# ── dropped messages are recorded as rejections (debug log) ──


def test_rejection_carries_subject_sender_and_reason():
    rej = _reject(_human(
        subject="Big Sale!!",
        sender="El equipo de Miro <your@product.miro.com>",
    ))
    assert len(rej) == 1
    r = rej[0]
    assert r.reason == "brandy_sender_name"
    assert r.subject == "Big Sale!!"
    assert r.sender == "your@product.miro.com"
    assert r.tenant_id == "T1" and r.mailbox == "me@acme.com"
    assert r.message_id  # non-empty, for the dedup key


def test_rejection_reason_codes_per_signal():
    cases = {
        "list_mail": _human(extra_headers={"List-Unsubscribe": "<mailto:u@x.com>"}),
        "bulk_precedence": _human(extra_headers={"Precedence": "bulk"}),
        "auto_submitted": _human(extra_headers={"Auto-Submitted": "auto-generated"}),
        "noreply_sender": _human(sender="Acme <no-reply@acme.com>"),
        "role_mailbox_sender": _human(sender="South Summit <info@southsummit.io>"),
        "brandy_sender_name": _human(sender="Fun.xyz <fun@swapped.com>"),
    }
    for expected, raw in cases.items():
        rej = _reject(raw)
        assert [r.reason for r in rej] == [expected], expected


def test_kept_message_produces_no_rejection():
    assert _reject(_human()) == []
