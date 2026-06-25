"""Step-1 email extraction: messages → graph ops (events, entities, edges).

`extract_graph` is the deterministic core. Given a batch of EmailMessage records
and the run's domain context it returns:
  - one `event` per message (subject-free label, direction + thread_id metadata)
  - `person`/`company` entities (deduped by canonical key)
  - edges: sender `sent` event; event `to`/`cc` recipient; person `affiliated_with` company
Company qualification: CRM-known domains always; non-CRM only if we sent outbound
to them. Free-mail and own-domain never become companies.
"""

from pipeline.adapters.email_entities import (
    correspondent_domains,
    extract_graph,
    message_key,
)
from pipeline.adapters.gmail import EmailMessage

OWN = {"kiboventures.com"}


def _msg(sender, to=None, cc=None, *, mid, subject="Subj", body="Body"):
    return EmailMessage(
        tenant_id="T1", mailbox="me@kiboventures.com", message_id=mid, thread_id="TH",
        occurred_at="2026-06-01T10:00:00+00:00", sender=sender, to=to or [], cc=cc or [],
        subject=subject, body=body,
    )


def _by_key(ents):
    return {e.canonical_key: e for e in ents}


def _edge_set(edges):
    return {(e.source, e.rel, e.target) for e in edges}


def test_message_key_matches_extract_graph():
    """The orchestration recomputes the same message canonical key the graph uses."""
    msgs = [_msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana")], mid="<a@x>")]
    g = extract_graph(msgs, crm_domains=set(), crm_names={}, own_domains=OWN)
    msg_ck = next(e.canonical_key for e in g.entities if e.type == "message")
    assert message_key("T1", "<a@x>") == msg_ck


def test_outbound_to_crm_domain_builds_person_company_and_edges():
    msgs = [_msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana")], mid="<a@x>")]
    g = extract_graph(
        msgs, crm_domains={"gohub.vc"}, crm_names={"gohub.vc": "GoHub Ventures"}, own_domains=OWN
    )
    ents = _by_key(g.entities)

    me = "person::me@kiboventures.com"
    ana = "person::ana@gohub.vc"
    gohub = "company::T1::gohub.vc"
    assert {me, ana, gohub} <= set(ents)
    assert ents[gohub].type == "company" and ents[gohub].label == "GoHub Ventures"
    # one event for the message
    events = [e for e in g.entities if e.type == "message"]
    assert len(events) == 1
    ev = events[0].canonical_key

    edges = _edge_set(g.edges)
    assert (me, "sent", ev) in edges                 # person -sent-> message
    assert (ev, "received", ana) in edges            # message -received-> person
    assert (ana, "affiliated_with", gohub) in edges
    # own-domain colleague gets no company
    assert "company::T1::kiboventures.com" not in ents
    # `about` is intentionally not emitted for now
    assert not any(e.rel == "about" for e in g.edges)


def test_own_domain_sender_has_no_company():
    msgs = [_msg(("me@kiboventures.com", "Me"), to=[("x@gmail.com", "X")], mid="<a@x>")]
    g = extract_graph(msgs, crm_domains=set(), crm_names={}, own_domains=OWN,
                      free_mail_domains={"gmail.com"})
    ents = _by_key(g.entities)
    assert "company::T1::kiboventures.com" not in ents
    assert "company::T1::gmail.com" not in ents          # free-mail recipient → no company
    assert "person::x@gmail.com" in ents


def test_non_crm_domain_needs_outbound_to_qualify():
    inbound = _msg(("pat@newvendor.io", "Pat"), to=[("me@kiboventures.com", None)], mid="<in@nv>")

    # inbound only → no company
    g1 = extract_graph([inbound], crm_domains=set(), crm_names={}, own_domains=OWN)
    assert "company::T1::newvendor.io" not in _by_key(g1.entities)

    # add an outbound to that domain → it qualifies
    outbound = _msg(("me@kiboventures.com", "Me"), to=[("pat@newvendor.io", "Pat")], mid="<out@k>")
    g2 = extract_graph([inbound, outbound], crm_domains=set(), crm_names={}, own_domains=OWN)
    ents = _by_key(g2.entities)
    assert ents["company::T1::newvendor.io"].label == "Newvendor"
    assert ("person::pat@newvendor.io", "affiliated_with", "company::T1::newvendor.io") in _edge_set(g2.edges)


def test_role_mailbox_recipient_is_company_not_person():
    msgs = [_msg(("me@kiboventures.com", "Me"), to=[("info@gohub.vc", "GoHub")], mid="<a@x>")]
    g = extract_graph(msgs, crm_domains={"gohub.vc"}, crm_names={"gohub.vc": "GoHub Ventures"},
                      own_domains=OWN)
    ents = _by_key(g.entities)
    # role mailbox → a company entity, never a person; no `about` edge for now.
    assert "person::info@gohub.vc" not in ents
    assert "company::T1::gohub.vc" in ents
    assert not any(e.rel == "received" for e in g.edges)
    assert not any(e.rel == "about" for e in g.edges)


def test_no_about_edges_are_emitted():
    msgs = [_msg(("me@kiboventures.com", "Me"), to=[("john@gmail.com", "John")], mid="<a@x>")]
    g = extract_graph(msgs, crm_domains=set(), crm_names={}, own_domains=OWN,
                      free_mail_domains={"gmail.com"})
    assert not any(e.rel == "about" for e in g.edges)


def test_event_is_per_message_subject_free_with_metadata():
    msgs = [
        _msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana")], mid="<a@x>",
             subject="Q3 secret terms"),
        _msg(("ana@gohub.vc", "Ana"), to=[("me@kiboventures.com", None)], mid="<b@x>",
             subject="Re: Q3 secret terms"),
    ]
    g = extract_graph(msgs, crm_domains={"gohub.vc"}, crm_names={}, own_domains=OWN)
    events = [e for e in g.entities if e.type == "message"]
    assert len(events) == 2                      # one per message, not one per thread
    for e in events:
        assert "secret" not in e.label.lower()   # subject stays private
        assert e.metadata["thread_id"] == "TH"
        assert e.metadata["direction"] in ("in", "out")
    # direction reflects who sent
    out_ev, in_ev = events[0], events[1]
    assert out_ev.metadata["direction"] == "out"
    assert in_ev.metadata["direction"] == "in"


def test_entities_are_deduped_across_messages():
    msgs = [
        _msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana")], mid="<a@x>"),
        _msg(("ana@gohub.vc", "Ana"), to=[("me@kiboventures.com", None)], mid="<b@x>"),
    ]
    g = extract_graph(msgs, crm_domains={"gohub.vc"}, crm_names={}, own_domains=OWN)
    keys = [e.canonical_key for e in g.entities]
    assert len(keys) == len(set(keys))           # no duplicate person/company nodes


def test_person_label_upgrades_to_real_name_across_messages():
    # ana first appears with no display name (label would be the email), then named
    msgs = [
        _msg(("ana@gohub.vc", None), to=[("me@kiboventures.com", None)], mid="<m1>"),
        _msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana García")], mid="<m2>"),
    ]
    g = extract_graph(msgs, crm_domains=set(), crm_names={}, own_domains=OWN)
    assert _by_key(g.entities)["person::ana@gohub.vc"].label == "Ana García"


def test_person_label_is_not_downgraded_to_email():
    msgs = [
        _msg(("me@kiboventures.com", "Me"), to=[("ana@gohub.vc", "Ana García")], mid="<m1>"),
        _msg(("ana@gohub.vc", None), to=[("me@kiboventures.com", None)], mid="<m2>"),
    ]
    g = extract_graph(msgs, crm_domains=set(), crm_names={}, own_domains=OWN)
    assert _by_key(g.entities)["person::ana@gohub.vc"].label == "Ana García"


def test_correspondent_domains_are_outbound_recipients():
    msgs = [
        _msg(("me@kiboventures.com", "Me"), to=[("a@vendor.io", "A")], cc=[("b@partner.co", "B")],
             mid="<out@k>"),
        _msg(("c@inboundonly.com", "C"), to=[("me@kiboventures.com", None)], mid="<in@x>"),
    ]
    corr = correspondent_domains(msgs, own_domains=OWN)
    assert corr == {"vendor.io", "partner.co"}    # inboundonly.com not included
