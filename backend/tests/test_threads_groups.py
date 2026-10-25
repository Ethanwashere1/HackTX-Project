"""Contract sections 6-7: chat threads, call links, the team page, leaving, connections, and that
contacts never reach non-members."""

import pytest
from sqlmodel import select

from app.models import Group, Message, Request, Thread
from tests.test_health_errors import assert_error
from tests.test_requests import (
    accept_ok,
    form_group,
    join,
    make_event,
    members,
    participants,
    send_ok,
    uid,
)


@pytest.fixture
def trio(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana, ben, cara = (login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara"))
    e = make_event(host)
    for c in (ana, ben, cara):
        join(c, e)
    return {"host": host, "event_id": e, "ana": ana, "ben": ben, "cara": cara}


def set_contacts(c, value: str) -> None:
    resp = c.put("/api/me/contacts", json={"contacts": [{"kind": "discord", "value": value}]})
    assert resp.status_code == 200, resp.text


# --- threads -------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [("get", "/api/threads/thr_x/messages"), ("post", "/api/threads/thr_x/messages"),
     ("post", "/api/threads/thr_x/call"), ("get", "/api/groups/grp_x"),
     ("patch", "/api/groups/grp_x"), ("post", "/api/groups/grp_x/leave"),
     ("get", "/api/events/evt_x/connections")],
)
def test_threads_and_groups_require_login(client, method, path):
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    assert_error(getattr(client, method)(path, **kwargs), 401, "unauthenticated")


def test_chat_on_a_request_thread(trio):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    thread_id = send_ok(ana, e, uid(ben))["thread_id"]
    resp = ana.post(f"/api/threads/{thread_id}/messages", json={"text": "  Hi!  "})
    assert resp.status_code == 201, resp.text
    m1 = resp.json()
    assert set(m1) == {"message_id", "sender_id", "text", "sent_at"}
    assert m1["message_id"].startswith("msg_") and m1["sender_id"] == uid(ana) and m1["text"] == "Hi!"
    assert m1["sent_at"].endswith("Z")
    m2 = ben.post(f"/api/threads/{thread_id}/messages", json={"text": "Hey"}).json()

    msgs = ben.get(f"/api/threads/{thread_id}/messages").json()["messages"]
    assert [m["message_id"] for m in msgs] == [m1["message_id"], m2["message_id"]]
    after = ana.get(f"/api/threads/{thread_id}/messages", params={"after": m1["message_id"]}).json()
    assert [m["message_id"] for m in after["messages"]] == [m2["message_id"]]
    assert ana.get(f"/api/threads/{thread_id}/messages?after={m2['message_id']}").json() == {"messages": []}
    limited = ana.get(f"/api/threads/{thread_id}/messages?limit=1").json()["messages"]
    assert [m["message_id"] for m in limited] == [m1["message_id"]]

    # Non-participants can't read, post or call.
    assert_error(cara.get(f"/api/threads/{thread_id}/messages"), 403, "forbidden")
    assert_error(cara.post(f"/api/threads/{thread_id}/messages", json={"text": "x"}), 403, "forbidden")
    assert_error(cara.post(f"/api/threads/{thread_id}/call"), 403, "forbidden")
    assert_error(cara.get("/api/threads/thr_nope/messages"), 404, "not_found")
    # Validation
    assert_error(ana.post(f"/api/threads/{thread_id}/messages", json={"text": "   "}), 422, "validation_error")
    assert_error(ana.post(f"/api/threads/{thread_id}/messages", json={"text": "x" * 4001}), 422, "validation_error")
    assert_error(ana.get(f"/api/threads/{thread_id}/messages?limit=0"), 422, "validation_error")


def test_call_url_is_stable_per_thread_and_unguessable(trio, db):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    t1 = send_ok(ana, e, uid(ben))["thread_id"]
    t2 = send_ok(ana, e, uid(cara))["thread_id"]
    url = ana.post(f"/api/threads/{t1}/call").json()["call_url"]
    assert url.startswith("https://meet.jit.si/squadup-")
    assert ben.post(f"/api/threads/{t1}/call").json()["call_url"] == url
    other = ana.post(f"/api/threads/{t2}/call").json()["call_url"]
    assert other != url
    # The room name has a random suffix beyond the thread id.
    room = url.rsplit("/", 1)[1]
    assert room.startswith("squadup-" + t1.replace("_", "") + "-") and len(room.rsplit("-", 1)[1]) >= 16
    # A thread without a stored room gets one on first call, then keeps it.
    thread = db.get(Thread, t2)
    thread.call_room = None
    db.add(thread)
    db.commit()
    fresh = ana.post(f"/api/threads/{t2}/call").json()["call_url"]
    assert fresh.startswith("https://meet.jit.si/squadup-") and fresh != other
    assert cara.post(f"/api/threads/{t2}/call").json()["call_url"] == fresh


def test_group_thread_follows_membership(trio, db):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    gid = form_group(ana, ben, e)
    thread_id = ana.get(f"/api/groups/{gid}").json()["thread_id"]
    assert thread_id and participants(db, thread_id) == {uid(ana), uid(ben)}
    assert ben.post(f"/api/threads/{thread_id}/messages", json={"text": "welcome"}).status_code == 201
    assert_error(cara.get(f"/api/threads/{thread_id}/messages"), 403, "forbidden")

    accept_ok(ana, send_ok(cara, e, gid, "group")["request_id"])
    # A new member sees the history.
    assert [m["text"] for m in cara.get(f"/api/threads/{thread_id}/messages").json()["messages"]] == ["welcome"]

    assert ben.post(f"/api/groups/{gid}/leave").status_code == 204
    assert participants(db, thread_id) == {uid(ana), uid(cara)}
    assert_error(ben.get(f"/api/threads/{thread_id}/messages"), 403, "forbidden")


# --- team page -----------------------------------------------------------------------------------

def test_team_page_for_members_only(trio, login_as):
    ana, ben, cara, host, e = trio["ana"], trio["ben"], trio["cara"], trio["host"], trio["event_id"]
    set_contacts(ana, "ana#1234")
    set_contacts(ben, "ben#5678")
    set_contacts(cara, "cara#9999")
    gid = form_group(ana, ben, e)

    body = ben.get(f"/api/groups/{gid}").json()
    assert set(body) == {"group_id", "event_id", "name", "thread_id", "members"}
    assert body["group_id"] == gid and body["event_id"] == e and body["name"].startswith("Team ")
    by_id = {m["user_id"]: m for m in body["members"]}
    assert set(by_id) == {uid(ana), uid(ben)}
    assert by_id[uid(ana)] == {"user_id": uid(ana), "name": "Ana", "summary": None,
                               "contacts": [{"kind": "discord", "value": "ana#1234"}]}

    for outsider in (cara, host, login_as("out@utexas.edu", "Out")):
        assert_error(outsider.get(f"/api/groups/{gid}"), 403, "forbidden")
    assert_error(ana.get("/api/groups/grp_nope"), 404, "not_found")


def test_team_page_shows_interview_summary(trio, db):
    from app.models import Profile

    ana, ben, e = trio["ana"], trio["ben"], trio["event_id"]
    profile = db.exec(select(Profile).where(Profile.user_id == uid(ana))).one()
    profile.summary = "Frontend dev who loves climate apps"
    db.add(profile)
    db.commit()
    gid = form_group(ana, ben, e)
    by_id = {m["user_id"]: m for m in ben.get(f"/api/groups/{gid}").json()["members"]}
    assert by_id[uid(ana)]["summary"] == "Frontend dev who loves climate apps"


def test_contacts_never_leak_to_non_members(trio):
    """A pending requester sees the group's names but never their contacts, anywhere."""
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    set_contacts(ana, "secret-ana-discord")
    set_contacts(ben, "secret-ben-discord")
    gid = form_group(ana, ben, e)
    req = send_ok(cara, e, gid, "group")
    ana.post(f"/api/threads/{req['thread_id']}/messages", json={"text": "hi cara"})

    seen = [
        cara.get("/api/requests?box=outgoing"), cara.get("/api/requests?box=incoming"),
        cara.get(f"/api/events/{e}"), cara.get(f"/api/events/{e}/connections"),
        cara.get(f"/api/threads/{req['thread_id']}/messages"), cara.get(f"/api/groups/{gid}"),
        cara.post(f"/api/threads/{req['thread_id']}/call"), cara.get("/api/me"),
    ]
    for resp in seen:
        assert "secret-" not in resp.text, resp.request.url
    # ...until the group accepts her.
    accept_ok(ben, req["request_id"])
    assert "secret-ana-discord" in cara.get(f"/api/groups/{gid}").text


def test_rename_group(trio):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    gid = form_group(ana, ben, e)
    resp = ben.patch(f"/api/groups/{gid}", json={"name": "  Team Nebula "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Team Nebula"
    assert ana.get(f"/api/groups/{gid}").json()["name"] == "Team Nebula"
    assert_error(cara.patch(f"/api/groups/{gid}", json={"name": "Hijacked"}), 403, "forbidden")
    assert_error(ana.patch(f"/api/groups/{gid}", json={"name": "  "}), 422, "validation_error")
    assert_error(ana.patch(f"/api/groups/{gid}", json={"name": "x" * 201}), 422, "validation_error")
    assert_error(ana.patch("/api/groups/grp_nope", json={"name": "X"}), 404, "not_found")


# --- leaving -------------------------------------------------------------------------------------

def test_leave_group(trio, db):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    gid = form_group(ana, ben, e)
    assert_error(cara.post(f"/api/groups/{gid}/leave"), 403, "forbidden")
    assert_error(cara.post("/api/groups/grp_nope/leave"), 404, "not_found")

    assert ana.post(f"/api/groups/{gid}/leave").status_code == 204
    assert members(db, gid) == {uid(ben)}
    assert_error(ana.get(f"/api/groups/{gid}"), 403, "forbidden")
    assert_error(ana.post(f"/api/groups/{gid}/leave"), 403, "forbidden")
    assert ana.get(f"/api/events/{e}").json()["my_membership"]["group_id"] is None
    assert ben.get(f"/api/groups/{gid}").status_code == 200


def test_last_member_leaving_deletes_group_thread_and_pending_requests(trio, db):
    ana, ben, cara, e = trio["ana"], trio["ben"], trio["cara"], trio["event_id"]
    gid = form_group(ana, ben, e)
    group_thread = db.get(Group, gid).thread_id
    ana.post(f"/api/threads/{group_thread}/messages", json={"text": "bye"})
    req = send_ok(cara, e, gid, "group")
    # Leaving members also drop out of pending request chats to the group.
    assert ana.post(f"/api/groups/{gid}/leave").status_code == 204
    assert uid(ana) not in participants(db, req["thread_id"])
    assert ben.post(f"/api/groups/{gid}/leave").status_code == 204

    db.expire_all()
    assert db.get(Group, gid) is None
    assert db.get(Thread, group_thread) is None
    assert db.exec(select(Message).where(Message.thread_id == group_thread)).all() == []
    assert db.get(Request, req["request_id"]) is None
    assert_error(cara.post(f"/api/requests/{req['request_id']}/accept"), 404, "not_found")
    assert_error(ana.get(f"/api/groups/{gid}"), 404, "not_found")
    assert ana.get(f"/api/events/{e}").json()["stats"]["groups_formed"] == 0
    # The earlier accepted request survives, without its group.
    out = ana.get("/api/requests?box=outgoing").json()["requests"]
    assert out[0]["status"] == "accepted" and out[0]["group_id"] is None


# --- connections ---------------------------------------------------------------------------------

def test_connections_list(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana, ben, cara = (login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara"))
    set_contacts(ben, "ben#5678")
    set_contacts(cara, "cara#9999")
    e = make_event(host, type="informal")
    for c in (ana, ben, cara):
        join(c, e)
    req = send_ok(ana, e, uid(ben))
    con_id = accept_ok(ben, req["request_id"])["connection_id"]
    pending = send_ok(ana, e, uid(cara))

    cons = ana.get(f"/api/events/{e}/connections").json()["connections"]
    assert len(cons) == 1
    c = cons[0]
    assert set(c) == {"connection_id", "user_id", "name", "summary", "contacts", "thread_id", "connected_at"}
    assert c["connection_id"] == con_id and c["user_id"] == uid(ben) and c["name"] == "Ben"
    assert c["contacts"] == [{"kind": "discord", "value": "ben#5678"}]
    assert c["thread_id"] == req["thread_id"] and c["connected_at"].endswith("Z")
    assert [x["user_id"] for x in ben.get(f"/api/events/{e}/connections").json()["connections"]] == [uid(ana)]
    # A pending request is not a connection: no contacts for cara's side.
    assert cara.get(f"/api/events/{e}/connections").json() == {"connections": []}
    assert "cara#9999" not in ana.get(f"/api/events/{e}/connections").text
    assert pending["status"] == "pending"

    outsider = login_as("out@utexas.edu", "Out")
    assert_error(outsider.get(f"/api/events/{e}/connections"), 403, "forbidden")
    assert_error(ana.get("/api/events/evt_nope/connections"), 404, "not_found")


def test_connections_empty_for_structured_events(trio):
    ana, ben, e = trio["ana"], trio["ben"], trio["event_id"]
    form_group(ana, ben, e)
    assert ana.get(f"/api/events/{e}/connections").json() == {"connections": []}
