"""Contract section 2: orgs, join requests per verification method, roster upload, the feed."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.models import OrgMember, OrgRosterEntry
from app.models.base import utcnow
from app.services import orgs as org_svc
from tests.test_events import informal, structured
from tests.test_health_errors import assert_error


def make_org(client, **overrides) -> str:
    body = {"name": "UT Austin", "verification": "manual"}
    body.update(overrides)
    resp = client.post("/api/orgs", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["verification"] == body["verification"]
    return resp.json()["org_id"]


def join(client, org_id, **body) -> str:
    resp = client.post(f"/api/orgs/{org_id}/join", json=body or None)
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


def upload(client, org_id, content: str | bytes, filename="roster.csv"):
    data = content.encode() if isinstance(content, str) else content
    return client.put(f"/api/orgs/{org_id}/roster", files={"file": (filename, data, "text/csv")})


def my_org(client, org_id) -> dict | None:
    return next((o for o in client.get("/api/orgs").json()["orgs"] if o["org_id"] == org_id), None)


def uid(client) -> str:
    return client.user["user_id"]


@pytest.fixture
def admin(login_as):
    return login_as("ana@utexas.edu", "Ana Ruiz")


# --- auth ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/orgs"), ("post", "/api/orgs"), ("patch", "/api/orgs/org_x"),
        ("post", "/api/orgs/org_x/join"), ("get", "/api/orgs/org_x/join-requests"),
        ("post", "/api/orgs/org_x/join-requests/usr_x/approve"),
        ("post", "/api/orgs/org_x/join-requests/usr_x/decline"),
        ("put", "/api/orgs/org_x/roster"), ("post", "/api/orgs/org_x/admins"),
        ("get", "/api/orgs/org_x/feed"),
    ],
)
def test_orgs_require_login(client, method, path):
    kwargs = {"json": {}} if method in ("post", "patch", "put") else {}
    assert_error(getattr(client, method)(path, **kwargs), 401, "unauthenticated")


def test_unknown_org(admin):
    assert_error(admin.post("/api/orgs/org_nope/join"), 404, "not_found")
    assert_error(admin.get("/api/orgs/org_nope/join-requests"), 404, "not_found")
    assert_error(upload(admin, "org_nope", "email\na@b.co\n"), 404, "not_found")
    assert_error(admin.get("/api/orgs/org_nope/feed"), 403, "not_org_member")


# --- create and list -----------------------------------------------------------------------------

def test_creator_becomes_approved_admin(admin, db):
    org_id = make_org(
        admin, verification="email_domain", email_domains=["@UTexas.EDU ", "utexas.edu"]
    )
    member = db.exec(select(OrgMember).where(OrgMember.org_id == org_id)).one()
    assert (member.user_id, member.role, member.status) == (uid(admin), "admin", "approved")
    assert my_org(admin, org_id) == {
        "org_id": org_id, "name": "UT Austin", "verification": "email_domain",
        "email_domains": ["utexas.edu"], "discoverable": True, "member_count": 1,
        "my_role": "admin", "my_status": "approved",
    }
    assert admin.get("/api/me").json()["orgs"] == [{"org_id": org_id, "name": "UT Austin"}]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "X", "verification": "email_domain"},
        {"name": "X", "verification": "email_domain", "email_domains": []},
        {"name": "X", "verification": "manual", "email_domains": ["not a domain"]},
        {"name": "X", "verification": "sso"},
        {"name": "  "},
    ],
)
def test_create_validation(admin, body):
    assert_error(admin.post("/api/orgs", json=body), 422, "validation_error")


def test_list_shows_discoverable_and_own_orgs(admin, login_as):
    public = make_org(admin, name="Public")
    hidden = make_org(admin, name="Hidden", discoverable=False)
    ben = login_as("ben@gmail.com", "Ben Li")
    assert my_org(ben, public)["my_status"] is None
    assert my_org(ben, public)["my_role"] is None
    assert my_org(ben, hidden) is None
    # A non-discoverable org is joined by link, then listed with the request's status.
    assert join(ben, hidden) == "pending"
    assert my_org(ben, hidden)["my_status"] == "pending"
    assert my_org(ben, hidden)["member_count"] == 1
    assert ben.get("/api/me").json()["orgs"] == []


# --- manual verification and admin decisions -----------------------------------------------------

def test_manual_always_waits_and_admin_approves(admin, login_as):
    # Even with a matching email domain listed, `manual` never auto-approves.
    org_id = make_org(admin, email_domains=["gmail.com"])
    ben = login_as("ben@gmail.com", "Ben Li")
    assert join(ben, org_id, message="CS junior") == "pending"
    assert join(ben, org_id) == "pending"  # asking again keeps one request (and its message)

    listed = admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"]
    assert [(r["user_id"], r["name"], r["email"], r["message"], r["roster_match"])
            for r in listed] == [(uid(ben), "Ben Li", "ben@gmail.com", "CS junior", None)]
    assert listed[0]["requested_at"].endswith("Z")

    resp = admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"user_id": uid(ben), "status": "approved"}
    assert my_org(ben, org_id)["my_status"] == "approved"
    assert admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"] == []
    approved = admin.get(f"/api/orgs/{org_id}/join-requests?status=approved").json()["requests"]
    assert {r["user_id"] for r in approved} == {uid(admin), uid(ben)}

    assert_error(admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/approve"),
                 409, "request_not_pending")
    assert_error(admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/decline"),
                 409, "request_not_pending")
    assert_error(ben.post(f"/api/orgs/{org_id}/join"), 409, "already_member")
    assert_error(admin.post(f"/api/orgs/{org_id}/join"), 409, "already_member")


def test_decline_and_request_again(admin, login_as):
    org_id = make_org(admin)
    ben = login_as("ben@gmail.com", "Ben Li")
    join(ben, org_id)
    resp = admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/decline")
    assert resp.json() == {"user_id": uid(ben), "status": "declined"}
    assert my_org(ben, org_id)["my_status"] == "declined"
    assert_error(ben.get(f"/api/orgs/{org_id}/feed"), 403, "not_org_member")
    declined = admin.get(f"/api/orgs/{org_id}/join-requests?status=declined").json()["requests"]
    assert [r["user_id"] for r in declined] == [uid(ben)]
    # A declined user may ask again; the request goes back to the admin.
    assert join(ben, org_id, message="please") == "pending"
    pending = admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"]
    assert [r["message"] for r in pending] == ["please"]


@pytest.mark.parametrize("method", ["email_domain", "roster"])
def test_request_after_decline_waits_for_admin_even_on_a_match(admin, login_as, method):
    org_id = make_org(admin)  # manual: the request waits and the admin declines it
    ben = login_as("ben@utexas.edu", "Ben Li")
    assert join(ben, org_id) == "pending"
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/decline")

    # Now ben matches the org's verification method...
    if method == "roster":
        upload(admin, org_id, "email\nben@utexas.edu\ncara@utexas.edu\n")
        settings = {"verification": "roster"}
    else:
        settings = {"verification": "email_domain", "email_domains": ["utexas.edu"]}
    assert admin.patch(f"/api/orgs/{org_id}", json=settings).status_code == 200
    assert my_org(ben, org_id)["my_status"] == "declined"
    # ...but asking again after a decline still goes to the admin queue,
    assert join(ben, org_id, message="I'm on the list") == "pending"
    assert join(ben, org_id) == "pending"
    # and so do later settings changes and roster uploads.
    assert admin.patch(f"/api/orgs/{org_id}", json=settings).status_code == 200
    if method == "roster":
        upload(admin, org_id, "email\ncara@utexas.edu\nben@utexas.edu\n")
    assert my_org(ben, org_id)["my_status"] == "pending"
    pending = admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"]
    assert [(r["user_id"], r["message"]) for r in pending] == [(uid(ben), "I'm on the list")]

    # A first request that matches is still auto-approved, and the admin can approve ben.
    assert join(login_as("cara@utexas.edu", "Cara"), org_id) == "approved"
    resp = admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/approve")
    assert resp.json() == {"user_id": uid(ben), "status": "approved"}


def test_only_admins_decide(admin, login_as):
    org_id = make_org(admin)
    ben = login_as("ben@gmail.com", "Ben Li")
    cara = login_as("cara@gmail.com", "Cara")
    dan = login_as("dan@gmail.com", "Dan")
    join(ben, org_id)
    join(cara, org_id)
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/approve")
    # ben: approved member; cara: pending; dan: not a member.
    for c in (ben, cara, dan):
        assert_error(c.get(f"/api/orgs/{org_id}/join-requests"), 403, "not_org_admin")
        for action in ("approve", "decline"):
            assert_error(c.post(f"/api/orgs/{org_id}/join-requests/{uid(cara)}/{action}"),
                         403, "not_org_admin")
        assert_error(c.patch(f"/api/orgs/{org_id}", json={"name": "Mine"}), 403, "not_org_admin")
        assert_error(upload(c, org_id, "email\ncara@gmail.com\n"), 403, "not_org_admin")
        assert_error(c.post(f"/api/orgs/{org_id}/admins", json={"user_id": uid(c)}),
                     403, "not_org_admin")
    assert my_org(cara, org_id)["my_status"] == "pending"
    assert_error(admin.post(f"/api/orgs/{org_id}/join-requests/{uid(dan)}/approve"),
                 404, "not_found")


def test_promote_admin(admin, login_as):
    org_id = make_org(admin)
    ben = login_as("ben@gmail.com", "Ben Li")
    cara = login_as("cara@gmail.com", "Cara")
    join(ben, org_id)
    join(cara, org_id)
    # Only approved members can be promoted.
    assert_error(admin.post(f"/api/orgs/{org_id}/admins", json={"user_id": uid(ben)}),
                 404, "not_found")
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(ben)}/approve")
    resp = admin.post(f"/api/orgs/{org_id}/admins", json={"user_id": uid(ben)})
    assert resp.json() == {"user_id": uid(ben), "role": "admin"}
    assert my_org(ben, org_id)["my_role"] == "admin"
    # The new admin can now approve.
    assert ben.post(f"/api/orgs/{org_id}/join-requests/{uid(cara)}/approve").status_code == 200


# --- email_domain verification -------------------------------------------------------------------

@pytest.mark.parametrize(
    "email,expected",
    [
        ("ben@utexas.edu", "approved"),
        ("BEN@UTEXAS.EDU", "approved"),
        ("ben@cs.utexas.edu", "approved"),  # subdomain of a listed domain
        ("ben@gmail.com", "pending"),
        ("ben@notutexas.edu", "pending"),
        ("ben@utexas.edu.evil.com", "pending"),
    ],
)
def test_email_domain(admin, login_as, email, expected):
    org_id = make_org(admin, verification="email_domain", email_domains=["utexas.edu"])
    ben = login_as(email, "Ben Li")
    assert join(ben, org_id) == expected
    assert my_org(ben, org_id)["my_status"] == expected


def test_patch_settings_approves_matching_pending(admin, login_as):
    org_id = make_org(admin)
    ben = login_as("ben@utexas.edu", "Ben Li")
    cara = login_as("cara@gmail.com", "Cara")
    assert join(ben, org_id) == "pending"
    assert join(cara, org_id) == "pending"
    assert_error(admin.patch(f"/api/orgs/{org_id}", json={"verification": "email_domain"}),
                 422, "validation_error")
    resp = admin.patch(f"/api/orgs/{org_id}", json={
        "name": "UT", "verification": "email_domain", "email_domains": ["utexas.edu"],
        "discoverable": False,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "org_id": org_id, "name": "UT", "verification": "email_domain",
        "email_domains": ["utexas.edu"], "discoverable": False, "member_count": 2,
        "my_role": "admin", "my_status": "approved",
    }
    assert my_org(ben, org_id)["my_status"] == "approved"
    assert my_org(cara, org_id)["my_status"] == "pending"
    # Removing the domains while email_domain is the method is rejected.
    assert_error(admin.patch(f"/api/orgs/{org_id}", json={"email_domains": []}),
                 422, "validation_error")


# --- roster verification -------------------------------------------------------------------------

def test_roster_upload_and_match(admin, login_as, db):
    org_id = make_org(admin, verification="roster")
    waiting = login_as("ben@gmail.com", "Ben Li")
    assert join(waiting, org_id) == "pending"

    csv_text = (
        "﻿Name , EMAIL\r\n"
        "Ben Li,BEN@gmail.com\r\n"
        "  Cara   JONES ,\r\n"          # name-only row
        "Dan Wu,dan@school.edu\r\n"     # has an email: matches by email only
        ",\r\n"                         # blank row, skipped
        "ben li,ben@gmail.com\r\n"      # duplicate
    )
    resp = upload(admin, org_id, csv_text)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"entries": 3}
    # The pending request that now matches is approved by the upload.
    assert my_org(waiting, org_id)["my_status"] == "approved"

    rows = db.exec(select(OrgRosterEntry).where(OrgRosterEntry.org_id == org_id)).all()
    assert sorted((r.name, r.name_normalized, r.email) for r in rows) == [
        ("Ben Li", "ben li", "ben@gmail.com"),
        ("Cara   JONES", "cara jones", None),
        ("Dan Wu", "dan wu", "dan@school.edu"),
    ]

    assert join(login_as("DAN@school.edu", "Daniel"), org_id) == "approved"
    # A name-only row is a hint for the admin, never an auto-approval (names are self-chosen).
    cara = login_as("cara@x.com", "cara jones")
    assert join(cara, org_id) == "pending"
    # The name matches, but that roster row has an email, so a different email waits.
    dan = login_as("dan.wu@gmail.com", "Dan Wu")
    assert join(dan, org_id) == "pending"
    eve = login_as("eve@x.com", "Eve")
    assert join(eve, org_id) == "pending"

    pending = admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"]
    assert [(r["user_id"], r["roster_match"]) for r in pending] == [
        (uid(cara), "name"), (uid(dan), None), (uid(eve), None)
    ]
    approved = admin.get(f"/api/orgs/{org_id}/join-requests?status=approved").json()["requests"]
    assert {r["email"]: r["roster_match"] for r in approved} == {
        "ana@utexas.edu": None, "ben@gmail.com": "email", "dan@school.edu": "email",
    }


def test_roster_name_match_cannot_be_spoofed(admin, login_as):
    """Anyone can set their Google display name to a listed name: that alone never gets them in."""
    org_id = make_org(admin, verification="roster")
    upload(admin, org_id, "name\nCara Jones\n")
    impostor = login_as("mallory@evil.com", "Cara Jones")
    assert join(impostor, org_id) == "pending"
    # Re-uploading or re-saving the settings doesn't approve the name match either.
    upload(admin, org_id, "name,email\nCara Jones,\n")
    admin.patch(f"/api/orgs/{org_id}", json={"verification": "roster"})
    assert my_org(impostor, org_id)["my_status"] == "pending"
    [req] = admin.get(f"/api/orgs/{org_id}/join-requests").json()["requests"]
    assert (req["user_id"], req["roster_match"]) == (uid(impostor), "name")
    # The admin decides.
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(impostor)}/decline")
    assert my_org(impostor, org_id)["my_status"] == "declined"


def test_roster_upload_replaces_list(admin, login_as):
    org_id = make_org(admin, verification="roster")
    assert upload(admin, org_id, "email\nold@x.com\nalso@x.com\n").json() == {"entries": 2}
    assert upload(admin, org_id, "email\nnew@x.com\n").json() == {"entries": 1}
    assert join(login_as("old@x.com", "Old"), org_id) == "pending"
    assert join(login_as("new@x.com", "New Person"), org_id) == "approved"


def test_roster_on_manual_org_does_not_auto_approve(admin, login_as):
    org_id = make_org(admin)
    ben = login_as("ben@gmail.com", "Ben Li")
    join(ben, org_id)
    assert upload(admin, org_id, "email\nben@gmail.com\n").json() == {"entries": 1}
    assert my_org(ben, org_id)["my_status"] == "pending"
    # Switching the method to roster applies the uploaded list to pending requests.
    admin.patch(f"/api/orgs/{org_id}", json={"verification": "roster"})
    assert my_org(ben, org_id)["my_status"] == "approved"


@pytest.mark.parametrize(
    "content,fragment",
    [
        ("", "empty"),
        ("first,last\nA,B\n", "column"),
        ("email,email\na@b.co,c@d.co\n", "duplicate"),
        ("email\nnot-an-email\n", "Line 2"),
        ("name\n" + "x" * 201 + "\n", "too long"),
        ("email\n" + "".join(f"u{i}@x.co\n" for i in range(org_svc.MAX_ROSTER_ROWS + 1)),
         "more than"),
        (b"name\n\xff\xfe\n", "UTF-8"),
    ],
    ids=["empty", "no_columns", "duplicate_columns", "bad_email", "long_name", "too_many_rows",
         "not_utf8"],
)
def test_roster_validation(admin, db, content, fragment):
    org_id = make_org(admin, verification="roster")
    upload(admin, org_id, "email\nkeep@x.com\n")
    resp = upload(admin, org_id, content)
    assert_error(resp, 422, "invalid_roster")
    assert fragment in resp.json()["error"]["message"]
    # A rejected upload leaves the previous roster in place.
    emails = db.exec(select(OrgRosterEntry.email).where(OrgRosterEntry.org_id == org_id)).all()
    assert emails == ["keep@x.com"]


def test_roster_upload_size_and_format(admin, monkeypatch):
    org_id = make_org(admin, verification="roster")
    big = "email\n" + "a" * (org_svc.MAX_ROSTER_BYTES + 10) + "@x.co\n"
    assert_error(upload(admin, org_id, big), 422, "invalid_roster")
    # A file just over the CSV cap that fits the overall upload cap is still rejected.
    monkeypatch.setattr(org_svc, "MAX_ROSTER_BYTES", 100)
    assert_error(upload(admin, org_id, "email\n" + "a" * 120 + "@x.co\n"), 422, "invalid_roster")
    assert_error(admin.put(f"/api/orgs/{org_id}/roster", content=b"email\na@b.co\n",
                           headers={"content-type": "text/csv"}), 422, "invalid_roster")
    resp = admin.put(f"/api/orgs/{org_id}/roster",
                     files={"other": ("r.csv", b"email\n", "text/csv")})
    assert_error(resp, 422, "invalid_roster")
    assert "file" in resp.json()["error"]["message"]


# --- feed and org events -------------------------------------------------------------------------

def test_feed_visible_only_to_approved_members(admin, login_as):
    org_id = make_org(admin)
    member = login_as("ben@gmail.com", "Ben Li")
    pending = login_as("cara@gmail.com", "Cara")
    declined = login_as("dan@gmail.com", "Dan")
    outsider = login_as("eve@gmail.com", "Eve")
    for c in (member, pending, declined):
        join(c, org_id)
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(member)}/approve")
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(declined)}/decline")

    for c in (pending, declined, outsider):
        assert_error(c.get(f"/api/orgs/{org_id}/feed"), 403, "not_org_member")
        assert_error(c.post("/api/events", json=informal(org_id=org_id)), 403, "not_org_member")
    for c in (admin, member):
        assert c.get(f"/api/orgs/{org_id}/feed").json() == {"org_id": org_id, "events": []}


def test_feed_lists_upcoming_org_events(admin, login_as):
    org_id = make_org(admin, verification="email_domain", email_domains=["utexas.edu"])
    other_org = make_org(admin, name="Other")
    ben = login_as("ben@utexas.edu", "Ben Li")
    assert join(ben, org_id) == "approved"

    def at(hours: float) -> str:
        return (utcnow() + timedelta(hours=hours)).isoformat()

    def create(client, body) -> str:
        resp = client.post("/api/events", json=body)
        assert resp.status_code == 201, resp.text
        return resp.json()["event_id"]

    # An approved (non-admin) member can create events in the org.
    later = create(ben, informal(org_id=org_id, name="Later", starts_at=at(48)))
    soon = create(admin, structured(org_id=org_id, name="Soon", starts_at=at(2),
                                    required_fields=[], questions=[]))
    unscheduled = create(admin, informal(org_id=org_id, name="Whenever"))
    started = create(admin, informal(org_id=org_id, name="Started", starts_at=at(-1)))
    create(admin, informal(org_id=org_id, name="Long past", starts_at=at(-48)))
    create(admin, informal(org_id=other_org, name="Elsewhere"))
    create(admin, informal(name="Unlisted"))
    assert ben.post(f"/api/events/{soon}/join", json={}).status_code == 201

    feed = ben.get(f"/api/orgs/{org_id}/feed").json()
    assert feed["org_id"] == org_id
    assert [e["event_id"] for e in feed["events"]] == [started, soon, later, unscheduled]
    by_id = {e["event_id"]: e for e in feed["events"]}
    assert by_id[soon] == {
        "event_id": soon, "name": "Soon", "type": "structured", "tone": "casual",
        "starts_at": by_id[soon]["starts_at"], "member_count": 1, "joined": True,
    }
    assert by_id[soon]["starts_at"].endswith("Z")
    assert by_id[unscheduled]["starts_at"] is None
    assert (by_id[later]["member_count"], by_id[later]["joined"]) == (0, False)
    assert admin.get(f"/api/orgs/{org_id}/feed").json()["events"][1]["joined"] is False
