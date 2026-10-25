"""Contract section 5: requests, mutual consent and the group/connection invariants."""

import pytest
from sqlmodel import select

from app.models import Connection, Group, GroupMember, OrgMember, Request, Thread, ThreadParticipant
from app.services.requests import excluded_for_viewer
from tests.test_events import make_org
from tests.test_health_errors import assert_error


# --- helpers -------------------------------------------------------------------------------------

def uid(c) -> str:
    return c.user["user_id"]


def make_event(host, *, type="structured", **settings) -> str:
    body = {"name": "HackTX team-up", "type": type, "tone": "casual"}
    if type == "structured":
        body.update({"group_count": 6, "min_size": 1, "max_size": 4, "max_groups_per_user": 1})
        body.update(settings)
    resp = host.post("/api/events", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["event_id"]


def join(c, event_id) -> None:
    resp = c.post(f"/api/events/{event_id}/join", json={})
    assert resp.status_code == 201, resp.text


def send(c, event_id, target, target_type="user", message="Want to team up?"):
    return c.post("/api/requests", json={
        "event_id": event_id, "target_type": target_type, "target_id": target, "message": message,
    })


def send_ok(c, event_id, target, target_type="user") -> dict:
    resp = send(c, event_id, target, target_type)
    assert resp.status_code == 201, resp.text
    return resp.json()


def accept_ok(c, request_id) -> dict:
    resp = c.post(f"/api/requests/{request_id}/accept")
    assert resp.status_code == 200, resp.text
    return resp.json()


def form_group(a, b, event_id) -> str:
    """a requests b, b accepts: returns the new group's id."""
    req = send_ok(a, event_id, uid(b))
    return accept_ok(b, req["request_id"])["group_id"]


def participants(db, thread_id) -> set[str]:
    return set(db.exec(select(ThreadParticipant.user_id).where(ThreadParticipant.thread_id == thread_id)).all())


def members(db, group_id) -> set[str]:
    return set(db.exec(select(GroupMember.user_id).where(GroupMember.group_id == group_id)).all())


@pytest.fixture
def people(login_as):
    """Host plus five users, all joined to one structured event (6 groups of up to 4, 1 each)."""
    host = login_as("host@utexas.edu", "Hannah Host")
    users = {n: login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara", "dan", "eve")}
    event_id = make_event(host)
    for c in users.values():
        join(c, event_id)
    return {"host": host, "event_id": event_id, **users}


# --- auth ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [("post", "/api/requests"), ("get", "/api/requests"), ("post", "/api/requests/req_x/accept"),
     ("post", "/api/requests/req_x/decline"), ("post", "/api/requests/req_x/cancel")],
)
def test_requests_require_login(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    assert_error(getattr(client, method)(path, **kwargs), 401, "unauthenticated")


def test_unknown_request_is_404(people):
    for verb in ("accept", "decline", "cancel"):
        assert_error(people["ana"].post(f"/api/requests/req_nope/{verb}"), 404, "not_found")


# --- sending -------------------------------------------------------------------------------------

def test_send_to_user_creates_pending_request_and_thread(people, db):
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    body = send_ok(ana, e, uid(ben))
    assert body["status"] == "pending"
    assert body["request_id"].startswith("req_") and body["thread_id"].startswith("thr_")
    assert participants(db, body["thread_id"]) == {uid(ana), uid(ben)}

    out = ana.get("/api/requests", params={"box": "outgoing"}).json()["requests"]
    assert len(out) == 1
    r = out[0]
    assert r["request_id"] == body["request_id"] and r["event_id"] == e
    assert r["sender"] == {"user_id": uid(ana), "name": "Ana"}
    assert r["target_type"] == "user" and r["target"] == {"user_id": uid(ben), "name": "Ben"}
    assert r["message"] == "Want to team up?" and r["status"] == "pending"
    assert r["thread_id"] == body["thread_id"]
    assert r["group_id"] is None and r["connection_id"] is None and r["decided_at"] is None

    assert [x["request_id"] for x in ben.get("/api/requests?box=incoming").json()["requests"]] == [body["request_id"]]
    assert ben.get("/api/requests?box=outgoing").json()["requests"] == []
    assert ana.get("/api/requests?box=incoming").json()["requests"] == []
    assert cara.get("/api/requests?box=incoming").json()["requests"] == []
    # event_id filter
    assert ben.get(f"/api/requests?box=incoming&event_id={e}").json()["requests"]
    assert ben.get("/api/requests?box=incoming&event_id=evt_other").json()["requests"] == []


def test_send_to_group_includes_all_current_members(people, db):
    ana, ben, cara, dan, e = people["ana"], people["ben"], people["cara"], people["dan"], people["event_id"]
    gid = form_group(ana, ben, e)
    body = send_ok(cara, e, gid, "group")
    assert participants(db, body["thread_id"]) == {uid(ana), uid(ben), uid(cara)}
    for member in (ana, ben):
        inc = [r for r in member.get("/api/requests?box=incoming").json()["requests"]
               if r["status"] == "pending"]
        assert [r["request_id"] for r in inc] == [body["request_id"]]
        assert inc[0]["target"]["group_id"] == gid and inc[0]["target"]["name"].startswith("Team ")
    assert dan.get("/api/requests?box=incoming").json()["requests"] == []


def test_send_validation(people, login_as, db):
    ana, ben, e = people["ana"], people["ben"], people["event_id"]
    outsider = login_as("out@utexas.edu", "Olive Outsider")
    assert_error(send(ana, e, uid(ana)), 422, "validation_error")  # yourself
    assert_error(send(ana, e, uid(outsider)), 404, "not_found")  # target not in the event
    assert_error(send(ana, e, "usr_nope"), 404, "not_found")
    assert_error(send(ana, "evt_nope", uid(ben)), 404, "not_found")
    assert_error(send(outsider, e, uid(ana)), 403, "forbidden")  # sender not in the event
    assert_error(send(ana, e, "grp_nope", "group"), 404, "not_found")
    assert_error(ana.post("/api/requests", json={"event_id": e, "target_type": "team", "target_id": uid(ben)}),
                 422, "validation_error")
    assert_error(send(ana, e, uid(ben), message="x" * 1001), 422, "validation_error")
    # A group from another event is not found here.
    other = make_event(people["host"])
    join(ana, other)
    join(ben, other)
    other_gid = form_group(ana, ben, other)
    assert_error(send(people["cara"], e, other_gid, "group"), 404, "not_found")
    # Can't request a group you're in.
    assert_error(send(ana, other, other_gid, "group"), 409, "already_in_group")


def test_send_in_org_event_needs_org_membership(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana = login_as("ana@utexas.edu", "Ana")
    ben = login_as("ben@utexas.edu", "Ben")
    org = make_org(db, {uid(host): "approved", uid(ana): "approved", uid(ben): "approved"})
    resp = host.post("/api/events", json={"org_id": org, "name": "E", "type": "informal", "tone": "casual"})
    e = resp.json()["event_id"]
    join(ana, e)
    join(ben, e)
    row = db.exec(select(OrgMember).where(OrgMember.user_id == uid(ana))).one()
    row.status = "declined"
    db.add(row)
    db.commit()
    assert_error(send(ana, e, uid(ben)), 403, "not_org_member")


def test_duplicate_pending_request_is_409_and_resend_after_decline_works(people):
    ana, ben, e = people["ana"], people["ben"], people["event_id"]
    first = send_ok(ana, e, uid(ben))
    assert_error(send(ana, e, uid(ben)), 409, "duplicate_request")
    assert ben.post(f"/api/requests/{first['request_id']}/decline").status_code == 200
    second = send_ok(ana, e, uid(ben))
    assert second["request_id"] != first["request_id"]


def test_duplicate_pending_group_request_is_409(people):
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    gid = form_group(ana, ben, e)
    send_ok(cara, e, gid, "group")
    assert_error(send(cara, e, gid, "group"), 409, "duplicate_request")


def test_informal_event_has_no_group_targets(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana = login_as("ana@utexas.edu", "Ana")
    e = make_event(host, type="informal")
    join(ana, e)
    assert_error(send(ana, e, "grp_x", "group"), 422, "validation_error")


# --- accepting -----------------------------------------------------------------------------------

def test_accept_user_to_user_forms_a_group(people, db):
    ana, ben, e = people["ana"], people["ben"], people["event_id"]
    req = send_ok(ana, e, uid(ben))
    body = accept_ok(ben, req["request_id"])
    assert body["request_id"] == req["request_id"] and body["status"] == "accepted"
    assert body["group_id"].startswith("grp_") and body["connection_id"] is None

    group = db.get(Group, body["group_id"])
    assert group.event_id == e and group.name.startswith("Team ") and len(group.name.split()) == 3
    assert members(db, group.id) == {uid(ana), uid(ben)}
    assert group.thread_id and group.thread_id != req["thread_id"]
    assert participants(db, group.thread_id) == {uid(ana), uid(ben)}

    stored = db.get(Request, req["request_id"])
    assert stored.decided_by == uid(ben) and stored.decided_at is not None and stored.group_id == group.id
    ev = ana.get(f"/api/events/{e}").json()
    assert ev["stats"]["groups_formed"] == 1 and ev["my_membership"]["group_id"] == group.id
    out = ana.get("/api/requests?box=outgoing").json()["requests"][0]
    assert out["status"] == "accepted" and out["group_id"] == group.id and out["decided_at"]


def test_accept_user_to_group_adds_the_sender(people, db):
    ana, ben, cara, dan, e = (people[k] for k in ("ana", "ben", "cara", "dan", "event_id"))
    gid = form_group(ana, ben, e)
    group = db.get(Group, gid)
    cara_req = send_ok(cara, e, gid, "group")
    dan_req = send_ok(dan, e, gid, "group")
    # Any current member can accept, not only the group's first member.
    body = accept_ok(ben, cara_req["request_id"])
    assert body == {"request_id": cara_req["request_id"], "status": "accepted", "group_id": gid, "connection_id": None}
    assert members(db, gid) == {uid(ana), uid(ben), uid(cara)}
    assert participants(db, group.thread_id) == {uid(ana), uid(ben), uid(cara)}
    # The new member joins the chats of other pending requests to the group, and can accept them.
    assert uid(cara) in participants(db, dan_req["thread_id"])
    assert dan_req["request_id"] in [r["request_id"] for r in cara.get("/api/requests?box=incoming").json()["requests"]]
    accept_ok(cara, dan_req["request_id"])
    assert members(db, gid) == {uid(ana), uid(ben), uid(cara), uid(dan)}


def test_accept_informal_creates_connection(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    ana, ben = login_as("ana@utexas.edu", "Ana"), login_as("ben@utexas.edu", "Ben")
    e = make_event(host, type="informal")
    join(ana, e)
    join(ben, e)
    req = send_ok(ana, e, uid(ben))
    body = accept_ok(ben, req["request_id"])
    assert body["group_id"] is None and body["connection_id"].startswith("con_")
    assert db.exec(select(Group)).all() == []
    cons = ana.get(f"/api/events/{e}/connections").json()["connections"]
    assert [c["connection_id"] for c in cons] == [body["connection_id"]]
    assert cons[0]["user_id"] == uid(ben) and cons[0]["thread_id"] == req["thread_id"]
    # The request's chat thread becomes the connection's thread; no group thread is made.
    assert participants(db, req["thread_id"]) == {uid(ana), uid(ben)}
    assert db.exec(select(Thread)).all() == [db.get(Thread, req["thread_id"])]
    # Already connected: a new request either way is refused.
    assert_error(send(ana, e, uid(ben)), 409, "already_connected")
    assert_error(send(ben, e, uid(ana)), 409, "already_connected")


@pytest.fixture
def informal(login_as):
    """Host plus ana, ben and cara, all joined to one informal event."""
    host = login_as("host@utexas.edu", "Hannah Host")
    users = {n: login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara")}
    event_id = make_event(host, type="informal")
    for c in users.values():
        join(c, event_id)
    return {"host": host, "event_id": event_id, **users}


@pytest.mark.parametrize("accept_first", ["ana_to_ben", "ben_to_ana"])
def test_crossing_informal_requests_connect_once(informal, db, accept_first):
    """ana and ben request each other: accepting either one accepts both, with one connection."""
    ana, ben, e = informal["ana"], informal["ben"], informal["event_id"]
    r1 = send_ok(ana, e, uid(ben))["request_id"]
    r2 = send_ok(ben, e, uid(ana))["request_id"]
    accepted, acceptor, other, other_acceptor = (
        (r1, ben, r2, ana) if accept_first == "ana_to_ben" else (r2, ana, r1, ben)
    )
    body = accept_ok(acceptor, accepted)
    con_id = body["connection_id"]
    assert body["status"] == "accepted" and con_id.startswith("con_") and body["group_id"] is None
    assert_error(other_acceptor.post(f"/api/requests/{other}/accept"), 409, "request_not_pending")
    assert_error(other_acceptor.post(f"/api/requests/{other}/decline"), 409, "request_not_pending")

    for rid in (r1, r2):
        stored = db.get(Request, rid)
        assert (stored.status, stored.connection_id, stored.decided_by) == ("accepted", con_id, uid(acceptor))
    assert len(db.exec(select(Connection)).all()) == 1
    assert db.get(Connection, con_id).thread_id == db.get(Request, accepted).thread_id
    for c, peer in ((ana, ben), (ben, ana)):
        cons = c.get(f"/api/events/{e}/connections").json()["connections"]
        assert [(x["connection_id"], x["user_id"]) for x in cons] == [(con_id, uid(peer))]
        listed = [r for box in ("incoming", "outgoing")
                  for r in c.get(f"/api/requests?box={box}&event_id={e}").json()["requests"]]
        assert {(r["status"], r["connection_id"]) for r in listed} == {("accepted", con_id)}


def test_crossing_resolution_leaves_other_pairs_alone(informal, db):
    ana, ben, cara, e = informal["ana"], informal["ben"], informal["cara"], informal["event_id"]
    r_ab = send_ok(ana, e, uid(ben))["request_id"]
    r_ca = send_ok(cara, e, uid(ana))["request_id"]
    r_ac = send_ok(ana, e, uid(cara))["request_id"]
    r_bc = send_ok(ben, e, uid(cara))["request_id"]
    accept_ok(ben, r_ab)
    assert {rid: db.get(Request, rid).status for rid in (r_ca, r_ac, r_bc)} == dict.fromkeys(
        (r_ca, r_ac, r_bc), "pending"
    )
    # A declined crossing request stays declined when the other direction is accepted.
    assert ana.post(f"/api/requests/{r_ca}/decline").status_code == 200
    con_id = accept_ok(cara, r_ac)["connection_id"]
    assert db.get(Request, r_ca).status == "declined" and db.get(Request, r_ca).connection_id is None
    assert db.get(Request, r_bc).status == "pending"
    assert {c["user_id"] for c in ana.get(f"/api/events/{e}/connections").json()["connections"]} == {
        uid(ben), uid(cara)
    }
    assert con_id in {c["connection_id"] for c in cara.get(f"/api/events/{e}/connections").json()["connections"]}


def test_accept_after_pair_already_connected_reuses_the_connection(informal, db):
    """A request that slipped in while another accept was committing resolves to the same connection."""
    ana, ben, e = informal["ana"], informal["ben"], informal["event_id"]
    con_id = accept_ok(ben, send_ok(ana, e, uid(ben))["request_id"])["connection_id"]
    late = Request(event_id=e, sender_id=uid(ben), target_type="user", target_user_id=uid(ana))
    db.add(late)
    db.commit()
    body = accept_ok(ana, late.id)
    assert body == {"request_id": late.id, "status": "accepted", "group_id": None, "connection_id": con_id}
    assert len(db.exec(select(Connection)).all()) == 1


def test_informal_decline_and_cancel_make_no_connection(informal, db):
    ana, ben, cara, e = informal["ana"], informal["ben"], informal["cara"], informal["event_id"]
    r1 = send_ok(ana, e, uid(ben))["request_id"]
    r2 = send_ok(ana, e, uid(cara))["request_id"]
    assert ben.post(f"/api/requests/{r1}/decline").json()["connection_id"] is None
    assert ana.post(f"/api/requests/{r2}/cancel").json()["connection_id"] is None
    assert db.exec(select(Connection)).all() == []
    assert ana.get(f"/api/events/{e}/connections").json() == {"connections": []}
    # Declined pairs are not recommended to each other.
    assert uid(ben) in excluded_for_viewer(db, e, uid(ana)).user_ids


def test_informal_group_target_rejected_even_for_a_real_group(people, informal):
    """A group id from a structured event can't be targeted from an informal one."""
    gid = form_group(people["ana"], people["ben"], people["event_id"])
    assert_error(send(informal["ana"], informal["event_id"], gid, "group"), 422, "validation_error")


def test_who_can_accept(people):
    ana, ben, cara, dan, e = (people[k] for k in ("ana", "ben", "cara", "dan", "event_id"))
    req = send_ok(ana, e, uid(ben))
    rid = req["request_id"]
    assert_error(ana.post(f"/api/requests/{rid}/accept"), 403, "forbidden")  # own request
    assert_error(cara.post(f"/api/requests/{rid}/accept"), 404, "not_found")  # unrelated
    assert_error(cara.post(f"/api/requests/{rid}/decline"), 404, "not_found")
    assert_error(cara.post(f"/api/requests/{rid}/cancel"), 404, "not_found")
    gid = accept_ok(ben, rid)["group_id"]
    # Group target: a non-member can't accept, the sender can't either.
    greq = send_ok(cara, e, gid, "group")
    assert_error(dan.post(f"/api/requests/{greq['request_id']}/accept"), 404, "not_found")
    assert_error(cara.post(f"/api/requests/{greq['request_id']}/accept"), 403, "forbidden")
    accept_ok(ana, greq["request_id"])


def test_request_not_pending(people):
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    rid = send_ok(ana, e, uid(ben))["request_id"]
    accept_ok(ben, rid)
    assert_error(ben.post(f"/api/requests/{rid}/accept"), 409, "request_not_pending")
    assert_error(ben.post(f"/api/requests/{rid}/decline"), 409, "request_not_pending")
    assert_error(ana.post(f"/api/requests/{rid}/cancel"), 409, "request_not_pending")

    rid2 = send_ok(cara, e, uid(people["dan"]))["request_id"]
    assert cara.post(f"/api/requests/{rid2}/cancel").json()["status"] == "cancelled"
    assert_error(people["dan"].post(f"/api/requests/{rid2}/accept"), 409, "request_not_pending")


def test_decline_and_cancel(people, db):
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    rid = send_ok(ana, e, uid(ben))["request_id"]
    assert_error(ana.post(f"/api/requests/{rid}/decline"), 403, "forbidden")  # sender cancels instead
    body = ben.post(f"/api/requests/{rid}/decline").json()
    assert body == {"request_id": rid, "status": "declined", "group_id": None, "connection_id": None}
    stored = db.get(Request, rid)
    assert stored.decided_by == uid(ben) and stored.decided_at is not None
    assert db.exec(select(Group)).all() == []

    rid2 = send_ok(ana, e, uid(cara))["request_id"]
    assert_error(cara.post(f"/api/requests/{rid2}/cancel"), 403, "forbidden")  # only the sender
    assert ana.post(f"/api/requests/{rid2}/cancel").json()["status"] == "cancelled"
    assert db.get(Request, rid2).decided_by == uid(ana)


# --- limits --------------------------------------------------------------------------------------

def test_group_full(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c = (login_as(f"{n}@x.edu", n) for n in ("a", "b", "c"))
    e = make_event(host, max_size=2)
    for u in (a, b, c):
        join(u, e)
    gid = form_group(a, b, e)
    rid = send_ok(c, e, gid, "group")["request_id"]
    assert_error(a.post(f"/api/requests/{rid}/accept"), 409, "group_full")
    assert members(db, gid) == {uid(a), uid(b)}
    assert db.get(Request, rid).status == "pending"  # a failed accept changes nothing


def test_group_full_when_max_size_is_one(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b = login_as("a@x.edu", "A"), login_as("b@x.edu", "B")
    e = make_event(host, max_size=1)
    join(a, e)
    join(b, e)
    rid = send_ok(a, e, uid(b))["request_id"]
    assert_error(b.post(f"/api/requests/{rid}/accept"), 409, "group_full")


def test_group_limit_reached(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c, d = (login_as(f"{n}@x.edu", n) for n in ("a", "b", "c", "d"))
    e = make_event(host, group_count=1)
    for u in (a, b, c, d):
        join(u, e)
    form_group(a, b, e)
    rid = send_ok(c, e, uid(d))["request_id"]
    assert_error(d.post(f"/api/requests/{rid}/accept"), 409, "group_limit_reached")
    assert len(db.exec(select(Group)).all()) == 1


def test_group_limit_per_user_at_one(people, db):
    ana, ben, cara, dan, eve, e = (people[k] for k in ("ana", "ben", "cara", "dan", "eve", "event_id"))
    gid = form_group(ana, ben, e)
    # user -> user where the target is already in a group
    rid = send_ok(cara, e, uid(ana))["request_id"]
    assert_error(ana.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    # user -> user where the sender is already in a group
    rid = send_ok(ben, e, uid(cara))["request_id"]
    assert_error(cara.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    # user -> group where the sender is already in another group
    gid2 = form_group(cara, dan, e)
    rid = send_ok(eve, e, gid2, "group")["request_id"]
    accept_ok(cara, rid)
    rid = send_ok(eve, e, gid, "group")["request_id"]
    assert_error(ana.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    assert members(db, gid) == {uid(ana), uid(ben)}


def test_group_limit_per_user_at_two(login_as, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c, d, f = (login_as(f"{n}@x.edu", n) for n in ("a", "b", "c", "d", "f"))
    e = make_event(host, max_groups_per_user=2)
    for u in (a, b, c, d, f):
        join(u, e)
    g1 = form_group(a, b, e)
    g2 = form_group(a, c, e)  # a is now in two groups: allowed
    assert {g1, g2} == set(db.exec(select(GroupMember.group_id).where(GroupMember.user_id == uid(a))).all())
    # A third group for a: refused whichever side a is on.
    rid = send_ok(a, e, uid(d))["request_id"]
    assert_error(d.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    rid = send_ok(d, e, uid(a))["request_id"]
    assert_error(a.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    g3 = form_group(d, f, e)
    rid = send_ok(a, e, g3, "group")["request_id"]
    assert_error(d.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    # b (one group) can still join a second one.
    rid = send_ok(b, e, g3, "group")["request_id"]
    accept_ok(f, rid)
    assert members(db, g3) == {uid(d), uid(f), uid(b)}


def test_already_in_group_on_accept(people, db):
    """Defensive check: the sender somehow became a member after sending."""
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    gid = form_group(ana, ben, e)
    rid = send_ok(cara, e, gid, "group")["request_id"]
    db.add(GroupMember(group_id=gid, event_id=e, user_id=uid(cara)))
    db.commit()
    assert_error(ana.post(f"/api/requests/{rid}/accept"), 409, "already_in_group")


def test_leaving_frees_the_slot(people):
    ana, ben, cara, e = people["ana"], people["ben"], people["cara"], people["event_id"]
    gid = form_group(ana, ben, e)
    rid = send_ok(cara, e, uid(ana))["request_id"]
    assert_error(ana.post(f"/api/requests/{rid}/accept"), 409, "group_limit_per_user")
    assert ana.post(f"/api/groups/{gid}/leave").status_code == 204
    assert accept_ok(ana, rid)["group_id"] != gid


# --- crossing requests in structured events ------------------------------------------------------

def pair_event(login_as, max_groups_per_user: int):
    """Host plus ana, ben, cara and dan, all joined to one structured event."""
    host = login_as("host@utexas.edu", "Hannah Host")
    users = [login_as(f"{n}@utexas.edu", n.capitalize()) for n in ("ana", "ben", "cara", "dan")]
    e = make_event(host, max_groups_per_user=max_groups_per_user)
    for c in users:
        join(c, e)
    return (*users, e)


def assert_settled(db, request_ids, group_id, decided_by) -> None:
    db.expire_all()
    for rid in request_ids:
        stored = db.get(Request, rid)
        assert (stored.status, stored.group_id, stored.decided_by) == ("accepted", group_id, decided_by)


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("accept_first", ["ana_to_ben", "ben_to_ana"])
def test_crossing_structured_requests_form_one_group(login_as, db, limit, accept_first):
    """ana and ben request each other: accepting either one accepts both, with one group."""
    ana, ben, _, _, e = pair_event(login_as, limit)
    r1 = send_ok(ana, e, uid(ben))["request_id"]
    r2 = send_ok(ben, e, uid(ana))["request_id"]
    accepted, acceptor, other, other_acceptor = (
        (r1, ben, r2, ana) if accept_first == "ana_to_ben" else (r2, ana, r1, ben)
    )
    gid = accept_ok(acceptor, accepted)["group_id"]
    assert_error(other_acceptor.post(f"/api/requests/{other}/accept"), 409, "request_not_pending")
    assert_error(other_acceptor.post(f"/api/requests/{other}/decline"), 409, "request_not_pending")

    assert_settled(db, [r1, r2], gid, uid(acceptor))
    assert [g.id for g in db.exec(select(Group)).all()] == [gid]
    assert members(db, gid) == {uid(ana), uid(ben)}
    for c in (ana, ben):
        listed = [r for box in ("incoming", "outgoing")
                  for r in c.get(f"/api/requests?box={box}&event_id={e}").json()["requests"]]
        assert {(r["status"], r["group_id"]) for r in listed} == {("accepted", gid)}
        assert c.get(f"/api/events/{e}").json()["my_membership"]["group_id"] == gid


def test_structured_crossing_leaves_other_pairs_alone(login_as, db):
    ana, ben, cara, dan, e = pair_event(login_as, 2)
    r_ab = send_ok(ana, e, uid(ben))["request_id"]
    r_ba = send_ok(ben, e, uid(ana))["request_id"]
    r_ca = send_ok(cara, e, uid(ana))["request_id"]
    r_ac = send_ok(ana, e, uid(cara))["request_id"]
    r_bc = send_ok(ben, e, uid(cara))["request_id"]
    r_dc = send_ok(dan, e, uid(cara))["request_id"]
    g1 = accept_ok(ben, r_ab)["group_id"]
    assert_settled(db, [r_ab, r_ba], g1, uid(ben))
    untouched = (r_ca, r_ac, r_bc, r_dc)
    assert {rid: db.get(Request, rid).status for rid in untouched} == dict.fromkeys(untouched, "pending")
    # A declined crossing request stays declined when the other direction is accepted.
    assert ana.post(f"/api/requests/{r_ca}/decline").status_code == 200
    g2 = accept_ok(cara, r_ac)["group_id"]
    assert g2 != g1 and members(db, g2) == {uid(ana), uid(cara)}
    db.expire_all()
    assert db.get(Request, r_ca).status == "declined" and db.get(Request, r_ca).group_id is None
    assert db.get(Request, r_bc).status == "pending" and db.get(Request, r_dc).status == "pending"


def test_joining_a_group_settles_requests_with_its_members(login_as, db):
    """cara joins ana and ben's group: her pending requests with them are accepted with that group;
    requests with people outside the group stay pending."""
    ana, ben, cara, dan, e = pair_event(login_as, 2)
    gid = form_group(ana, ben, e)
    r_join = send_ok(cara, e, gid, "group")["request_id"]
    r_ac = send_ok(ana, e, uid(cara))["request_id"]
    r_cb = send_ok(cara, e, uid(ben))["request_id"]
    r_dc = send_ok(dan, e, uid(cara))["request_id"]
    r_da = send_ok(dan, e, uid(ana))["request_id"]
    assert accept_ok(ben, r_join)["group_id"] == gid
    assert_settled(db, [r_join, r_ac, r_cb], gid, uid(ben))
    assert db.get(Request, r_dc).status == "pending" and db.get(Request, r_da).status == "pending"
    assert members(db, gid) == {uid(ana), uid(ben), uid(cara)}
    assert len(db.exec(select(Group)).all()) == 1


def test_request_to_a_group_mate_is_refused(login_as):
    ana, ben, cara, _, e = pair_event(login_as, 2)
    form_group(ana, ben, e)
    assert_error(send(ana, e, uid(ben)), 409, "already_in_group")
    assert_error(send(ben, e, uid(ana)), 409, "already_in_group")
    send_ok(ana, e, uid(cara))  # not group-mates: fine


@pytest.mark.parametrize("limit", [1, 2])
def test_accept_between_group_mates_reuses_the_group(login_as, db, limit):
    """A request that slipped in while the pair's group formed resolves to that group."""
    ana, ben, _, _, e = pair_event(login_as, limit)
    gid = form_group(ana, ben, e)
    late = Request(event_id=e, sender_id=uid(ben), target_type="user", target_user_id=uid(ana))
    db.add(late)
    db.commit()
    body = accept_ok(ana, late.id)
    assert body == {"request_id": late.id, "status": "accepted", "group_id": gid, "connection_id": None}
    assert [g.id for g in db.exec(select(Group)).all()] == [gid]
    assert members(db, gid) == {uid(ana), uid(ben)}


def test_late_request_after_a_leave_forms_a_new_group(login_as, db):
    """The pair no longer shares a group, so the late request forms one as usual."""
    ana, ben, _, _, e = pair_event(login_as, 1)
    gid = form_group(ana, ben, e)
    late = Request(event_id=e, sender_id=uid(ben), target_type="user", target_user_id=uid(ana))
    db.add(late)
    db.commit()
    assert ana.post(f"/api/groups/{gid}/leave").status_code == 204
    # ben is still in gid, so a new group would put him over his limit of 1.
    assert_error(ana.post(f"/api/requests/{late.id}/accept"), 409, "group_limit_per_user")
    assert ben.post(f"/api/groups/{gid}/leave").status_code == 204
    new_gid = accept_ok(ana, late.id)["group_id"]
    assert new_gid != gid and members(db, new_gid) == {uid(ana), uid(ben)}


# --- exclusions for recommendations --------------------------------------------------------------

def test_excluded_for_viewer(people, db):
    ana, ben, cara, dan, eve, e = (people[k] for k in ("ana", "ben", "cara", "dan", "eve", "event_id"))
    gid = form_group(ana, ben, e)
    # cara declined ana; ana declined dan (as the target); eve declined by the group (ben decides)
    r = send_ok(ana, e, uid(cara))["request_id"]
    cara.post(f"/api/requests/{r}/decline")
    r = send_ok(dan, e, uid(ana))["request_id"]
    ana.post(f"/api/requests/{r}/decline")
    r = send_ok(eve, e, gid, "group")["request_id"]
    ben.post(f"/api/requests/{r}/decline")

    ex = excluded_for_viewer(db, e, uid(ana))
    assert ex.user_ids == {uid(ana), uid(ben), uid(cara), uid(dan), uid(eve)}
    assert ex.group_ids == {gid}

    ex = excluded_for_viewer(db, e, uid(eve))
    assert ex.user_ids == {uid(eve)} and ex.group_ids == {gid}  # her request to the group was declined

    ex = excluded_for_viewer(db, e, uid(cara))
    assert ex.user_ids == {uid(cara), uid(ana)} and ex.group_ids == set()

    # Pending and cancelled requests don't exclude anyone.
    r = send_ok(cara, e, uid(dan))["request_id"]
    cara.post(f"/api/requests/{r}/cancel")
    assert excluded_for_viewer(db, e, uid(dan)).user_ids == {uid(dan), uid(ana)}
