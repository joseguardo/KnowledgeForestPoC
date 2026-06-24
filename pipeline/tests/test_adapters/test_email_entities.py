"""Step-1 email extraction: address → person/company classification.

Pure-function rules (no I/O):
  - human address          → person (+ company iff its domain qualifies)
  - role mailbox (info@…)  → the company itself, no person (iff domain qualifies)
  - free-mail domain       → person only, never a company
  - own firm domain        → colleague: person only, no company
  - noise (no-reply@…)     → skipped entirely
A domain *qualifies* as a company when it is known to the CRM, or we have
corresponded outbound to it.
"""

from pipeline.adapters.email_entities import (
    CompanyRef,
    PersonRef,
    classify_address,
    derive_company_label,
)

CRM = {"gohub.vc"}
CORRESPONDENTS = {"newvendor.io"}
OWN = {"kiboventures.com"}
NAMES = {"gohub.vc": "GoHub Ventures"}


def _classify(addr, name=None, **over):
    kw = dict(
        crm_domains=CRM,
        correspondent_domains=CORRESPONDENTS,
        own_domains=OWN,
        crm_names=NAMES,
    )
    kw.update(over)
    return classify_address(addr, name, **kw)


def test_human_at_crm_domain_is_person_with_company():
    c = _classify("ana@gohub.vc", "Ana García")
    assert c.person == PersonRef(email="ana@gohub.vc", name="Ana García")
    # company uses the CRM display name, keyed by domain
    assert c.company == CompanyRef(domain="gohub.vc", label="GoHub Ventures")


def test_role_mailbox_is_company_not_person():
    c = _classify("info@gohub.vc", "GoHub Info")
    assert c.person is None
    assert c.company == CompanyRef(domain="gohub.vc", label="GoHub Ventures")


def test_human_at_free_mail_is_person_only():
    c = _classify("ana@gmail.com", "Ana García", free_mail_domains={"gmail.com"})
    assert c.person == PersonRef(email="ana@gmail.com", name="Ana García")
    assert c.company is None


def test_noise_address_is_skipped():
    c = _classify("no-reply@gohub.vc", "GoHub")
    assert c.person is None and c.company is None


def test_human_at_own_domain_is_colleague_no_company():
    c = _classify("jose@kiboventures.com", "Jose")
    assert c.person == PersonRef(email="jose@kiboventures.com", name="Jose")
    assert c.company is None


def test_human_at_unknown_external_domain_has_no_company():
    # not in CRM, never corresponded → person only
    c = _classify("x@stripe.com", "Stripe Bot")
    assert c.person == PersonRef(email="x@stripe.com", name="Stripe Bot")
    assert c.company is None


def test_human_at_correspondent_domain_gets_company():
    c = _classify("x@newvendor.io", "Pat")
    assert c.person == PersonRef(email="x@newvendor.io", name="Pat")
    assert c.company == CompanyRef(domain="newvendor.io", label="Newvendor")


def test_role_mailbox_at_unqualified_domain_is_skipped():
    # info@ at a domain that is neither CRM nor a correspondent → nothing
    c = _classify("info@stripe.com", "Stripe")
    assert c.person is None and c.company is None


def test_address_is_lowercased_and_trimmed():
    c = _classify("  Ana@GoHub.VC ", "Ana")
    assert c.person == PersonRef(email="ana@gohub.vc", name="Ana")
    assert c.company == CompanyRef(domain="gohub.vc", label="GoHub Ventures")


def test_blank_or_malformed_address_is_skipped():
    assert classify_address("", None, crm_domains=set(), correspondent_domains=set(), own_domains=set()).person is None
    assert classify_address("notanemail", None, crm_domains=set(), correspondent_domains=set(), own_domains=set()).company is None


def test_derive_company_label_from_domain():
    assert derive_company_label("newvendor.io") == "Newvendor"
    assert derive_company_label("tin-capital.vc") == "Tin-Capital"
