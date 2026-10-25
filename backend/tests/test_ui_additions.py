"""Endpoints and fields added for the frontend (CONTRACT v1.0-pre.7): the org name in the feed,
GET /api/orgs/{id}, GET /api/threads/{id} with message sender names, GET /api/me/profile, and the
viewer-relative fields of the requests list."""

import pytest
from sqlmodel import select

from app.models import Profile
from tests.test_health_errors import assert_error
from tests.test_orgs import join as join_org
from tests.test_orgs import make_org, my_org
from tests.test_requests import accept_ok, form_group, join, make_event, send_ok, uid


@pytest.mark.parametrize(
    "path", ["/api/orgs/org_x", "/api/threads/thr_x", "/api/me/profile"]
)
def test_new_endpoints_require_login(client, path):
    assert_error(client.get(path), 401, "unauthenticated")


# --- orgs ----------------------------------------------------------------------------------------

def test_feed_includes_org_name(login_as):
    admin = login_as("ana@utexas.edu", "Ana Ruiz")
    org_id = make_org(admin, name="UT Austin")
    feed = admin.get(f"/api/orgs/{org_id}/feed").json()
    assert feed == {"org_id": org_id, "name": "UT Austin", "events": []}


def test_get_org_matches_the_list_item(login_as):
    admin = login_as("ana@utexas.edu", "Ana Ruiz")
    outsider = login_as("eve@gmail.com", "Eve")
    org_id = make_org(admin, verification="email_domain", email_domains=["utexas.edu"])

    body = admin.get(f"/api/orgs/{org_id}").json()
    assert body == my_org(admin, org_id)
    assert body == {
        "org_id": org_id, "name": "UT Austin", "verification": "email_domain",
        "email_domains": ["utexas.edu"], "discoverable": True, "member_count": 1,
        "my_role": "admin", "my_status": "approved",
    }
    # A discoverable org is visible to anyone signed in, without a role or status.
    seen = outsider.get(f"/api/orgs/{org_id}").json()
    assert seen == my_org(outsider, org_id)
    assert seen["my_role"] is None and seen["my_status"] is None


def test_hidden_org_is_404_unless_the_user_has_a_membership_row(login_as):
    admin = login_as("ana@utexas.edu", "Ana Ruiz")
    pending, declined, outsider = (
        login_as(f"{n}@gmail.com", n.capitalize()) for n in ("ben", "cara", "eve")
    )
    org_id = make_org(admin, discoverable=False)
    join_org(pending, org_id)
    join_org(declined, org_id)
    admin.post(f"/api/orgs/{org_id}/join-requests/{uid(declined)}/decline")

    # Hidden orgs look exactly like unknown ones to outsiders.
    assert_error(outsider.get(f"/api/orgs/{org_id}"), 404, "not_found")
    assert_error(outsider.get("/api/orgs/org_nope"), 404, "not_found")
    assert pending.get(f"/api/orgs/{org_id}").json()["my_status"] == "pending"
    assert declined.get(f"/api/orgs/{org_id}").json()["my_status"] == "declined"
    assert admin.get(f"/api/orgs/{org_id}").json()["discoverable"] is False


# --- threads -------------------------------------------------------------------------------------

@pytest.fixture
def squad(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    users = {n: login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara", "dan")}
    event_id = make_event(host)
    for c in users.values():
        join(c, event_id)
    return {"event_id": event_id, **users}


def thread(c, thread_id) -> dict:
    resp = c.get(f"/api/threads/{thread_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_request_thread_title_is_the_other_person(squad):
    ana, ben, cara, e = squad["ana"], squad["ben"], squad["cara"], squad["event_id"]
    req = send_ok(ana, e, uid(ben))
    mine = thread(ana, req["thread_id"])
    assert mine == {
        "thread_id": req["thread_id"], "kind": "request", "title": "Ben", "event_id": e,
        "group_id": None, "request_id": req["request_id"],
        "participants": [{"user_id": uid(ana), "name": "Ana"}, {"user_id": uid(ben), "name": "Ben"}],
    }
    theirs = thread(ben, req["thread_id"])
    assert theirs["title"] == "Ana"
    assert {k: v for k, v in theirs.items() if k != "title"} == {
        k: v for k, v in mine.items() if k != "title"
    }
    # Same access rule and errors as GET /messages.
    assert_error(cara.get(f"/api/threads/{req['thread_id']}"), 403, "forbidden")
    assert_error(cara.get("/api/threads/thr_nope"), 404, "not_found")


def test_group_thread_and_group_request_thread(squad):
    ana, ben, cara, dan, e = (squad[k] for k in ("ana", "ben", "cara", "dan", "event_id"))
    gid = form_group(ana, ben, e)
    group = ana.get(f"/api/groups/{gid}").json()
    g = thread(ben, group["thread_id"])
    assert g["kind"] == "group" and g["title"] == group["name"]
    assert g["group_id"] == gid and g["request_id"] is None and g["event_id"] == e
    assert {p["user_id"] for p in g["participants"]} == {uid(ana), uid(ben)}
    assert_error(cara.get(f"/api/threads/{group['thread_id']}"), 403, "forbidden")

    # user -> group: the sender sees the group's name, the group's members see the sender's.
    req = send_ok(cara, e, gid, "group")
    for_sender = thread(cara, req["thread_id"])
    assert for_sender["kind"] == "request" and for_sender["title"] == group["name"]
    assert for_sender["group_id"] == gid and for_sender["request_id"] == req["request_id"]
    assert thread(ana, req["thread_id"])["title"] == "Cara"
    assert thread(ben, req["thread_id"])["title"] == "Cara"
    assert_error(dan.get(f"/api/threads/{req['thread_id']}"), 403, "forbidden")

    # After the accept, the newcomer is in the group thread too.
    accept_ok(ana, req["request_id"])
    assert {p["name"] for p in thread(cara, group["thread_id"])["participants"]} == {"Ana", "Ben", "Cara"}


def test_connection_thread(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana, ben = login_as("ana@utexas.edu", "Ana"), login_as("ben@utexas.edu", "Ben")
    e = make_event(host, type="informal")
    join(ana, e)
    join(ben, e)
    req = send_ok(ana, e, uid(ben))
    assert thread(ana, req["thread_id"])["kind"] == "request"
    accept_ok(ben, req["request_id"])
    for viewer, other in ((ana, "Ben"), (ben, "Ana")):
        t = thread(viewer, req["thread_id"])
        assert t["kind"] == "connection" and t["title"] == other
        assert t["request_id"] == req["request_id"] and t["group_id"] is None
    assert_error(host.get(f"/api/threads/{req['thread_id']}"), 403, "forbidden")


def test_messages_carry_the_sender_name(squad):
    ana, ben, e = squad["ana"], squad["ben"], squad["event_id"]
    thread_id = send_ok(ana, e, uid(ben))["thread_id"]
    posted = ana.post(f"/api/threads/{thread_id}/messages", json={"text": "Hi"}).json()
    assert posted["sender_name"] == "Ana"
    assert set(posted) == {"message_id", "sender_id", "sender_name", "text", "sent_at"}
    ben.post(f"/api/threads/{thread_id}/messages", json={"text": "Hey"})
    msgs = ben.get(f"/api/threads/{thread_id}/messages").json()["messages"]
    assert [(m["sender_id"], m["sender_name"]) for m in msgs] == [(uid(ana), "Ana"), (uid(ben), "Ben")]


# --- my profile ----------------------------------------------------------------------------------

def test_my_profile_before_joining_anything(login_as):
    ana = login_as("ana@utexas.edu", "Ana Ruiz")
    assert ana.get("/api/me/profile").json() == {
        "user_id": uid(ana), "name": "Ana Ruiz", "email": "ana@utexas.edu", "overview": None, "summary": None,
        "traits": None, "socials": [], "contacts": [], "interviewed": False,
    }


def test_my_profile_shows_own_data_without_notes_or_transcript(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana, ben = login_as("ana@utexas.edu", "Ana"), login_as("ben@utexas.edu", "Ben")
    e = make_event(host)
    resp = ana.post(f"/api/events/{e}/join", json={"socials": [{"kind": "github", "value": "ana-r"}]})
    assert resp.status_code == 201, resp.text
    ana.put("/api/me/contacts", json={"contacts": [{"kind": "discord", "value": "ana#1"}]})
    profile = db.exec(select(Profile).where(Profile.user_id == uid(ana))).one()
    profile.summary = "Frontend dev"
    profile.traits = {"ambition": "win"}
    profile.social_notes = "SECRET NOTES"
    profile.transcript = [{"role": "user", "text": "SECRET TRANSCRIPT", "ts": "x"}]
    db.add(profile)
    db.commit()

    body = ana.get("/api/me/profile").json()
    assert body == {
        "user_id": uid(ana), "name": "Ana", "email": "ana@utexas.edu", "overview": None, "summary": "Frontend dev",
        "traits": {"ambition": "win"}, "socials": [{"kind": "github", "value": "ana-r"}],
        "contacts": [{"kind": "discord", "value": "ana#1"}], "interviewed": True,
    }
    assert "SECRET" not in str(body)
    # Each user only ever sees their own profile.
    assert ben.get("/api/me/profile").json()["user_id"] == uid(ben)
    assert "SECRET" not in ben.get("/api/me/profile").text


# --- requests list -------------------------------------------------------------------------------

def requests(c, box) -> list[dict]:
    return c.get("/api/requests", params={"box": box}).json()["requests"]


def test_requests_list_has_direction_and_other_party(squad):
    ana, ben, cara, dan, e = (squad[k] for k in ("ana", "ben", "cara", "dan", "event_id"))
    to_ben = send_ok(cara, e, uid(ben))
    out = requests(cara, "outgoing")[0]
    assert out["direction"] == "outgoing"
    assert out["other_party"] == {"type": "user", "id": uid(ben), "name": "Ben"}
    inc = requests(ben, "incoming")[0]
    assert inc["request_id"] == to_ben["request_id"] and inc["direction"] == "incoming"
    assert inc["other_party"] == {"type": "user", "id": uid(cara), "name": "Cara"}
    for item in (out, inc):
        assert {"event_id", "status", "thread_id", "created_at", "sender", "target"} <= set(item)

    gid = form_group(ana, dan, e)
    name = ana.get(f"/api/groups/{gid}").json()["name"]
    send_ok(cara, e, gid, "group")
    out_g = next(r for r in requests(cara, "outgoing") if r["target_type"] == "group")
    assert out_g["other_party"] == {"type": "group", "id": gid, "name": name}
    inc_g = requests(dan, "incoming")[0]
    assert inc_g["direction"] == "incoming"
    assert inc_g["other_party"] == {"type": "user", "id": uid(cara), "name": "Cara"}
