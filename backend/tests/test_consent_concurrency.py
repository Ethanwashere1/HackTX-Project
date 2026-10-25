"""Group limits and one-connection-per-pair hold when requests race: real threads, each with its own
DB session and transaction.

Each test widens the window between the checks and the write (a sleep before the member row is
added, before the connection lookup, or before a request's thread is made), so without the locks
and unique indexes both calls would pass their checks and the invariant would break.
"""

import threading
import time
from collections.abc import Callable

import pytest
from sqlmodel import Session, select

from app import db as dbmod
from app.errors import AppError
from app.models import Connection, Group, GroupMember, Request, User
from app.services import requests as svc
from tests.test_requests import form_group, join, make_event, members, send_ok, uid


def at_once(calls: list[tuple[str, Callable[[Session, User], object]]]) -> list[str]:
    """Run each call(session, user) for (user_id, call) at the same moment, one thread and DB session
    each. Returns each call's outcome: "ok" or the error code."""
    barrier = threading.Barrier(len(calls))
    results: list[str | None] = [None] * len(calls)

    def run(i: int, user_id: str, call) -> None:
        with Session(dbmod.get_engine()) as s:
            user = s.get(User, user_id)
            barrier.wait()
            try:
                call(s, user)
                results[i] = "ok"
            except AppError as exc:
                results[i] = exc.code
            except Exception as exc:  # noqa: BLE001 - surfaced in the assertion
                results[i] = repr(exc)

    threads = [threading.Thread(target=run, args=(i, *c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "deadlocked"
    return results


def slow_down(monkeypatch, name: str) -> None:
    """Sleep before svc.<name> runs, to widen the window between the checks and the write."""
    real = getattr(svc, name)

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(svc, name, slow)


@pytest.fixture
def race(monkeypatch):
    slow_down(monkeypatch, "_add_member")

    def _race(attempts: list[tuple[str, str]]) -> list[str]:
        """Run accept_request(request_id, by user_id) for all attempts at once."""
        return at_once([
            (user_id, lambda s, u, rid=request_id: svc.accept_request(s, rid, u))
            for request_id, user_id in attempts
        ])

    return _race


def users(login_as, n: int):
    return [login_as(f"u{i}@x.edu", f"User {i}") for i in range(n)]


def test_two_accepts_into_the_last_slot(login_as, race, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c, d = users(login_as, 4)
    e = make_event(host, max_size=3)
    for u in (a, b, c, d):
        join(u, e)
    gid = form_group(a, b, e)
    rc = send_ok(c, e, gid, "group")["request_id"]
    rd = send_ok(d, e, gid, "group")["request_id"]
    # Different acceptors, so only the group (and event) locks can serialize them.
    results = race([(rc, uid(a)), (rd, uid(b))])
    assert sorted(results) == ["group_full", "ok"], results
    assert len(members(db, gid)) == 3


def test_two_accepts_over_max_groups_per_user(login_as, race, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c, d, x = users(login_as, 5)
    e = make_event(host, max_groups_per_user=1)
    for u in (a, b, c, d, x):
        join(u, e)
    g1 = form_group(a, b, e)
    g2 = form_group(c, d, e)
    r1 = send_ok(x, e, g1, "group")["request_id"]
    r2 = send_ok(x, e, g2, "group")["request_id"]
    results = race([(r1, uid(a)), (r2, uid(c))])
    assert sorted(results) == ["group_limit_per_user", "ok"], results
    assert len(db.exec(select(GroupMember).where(GroupMember.user_id == uid(x))).all()) == 1


def test_two_new_groups_for_the_last_group_slot(login_as, race, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c, d = users(login_as, 4)
    e = make_event(host, group_count=1)
    for u in (a, b, c, d):
        join(u, e)
    r1 = send_ok(a, e, uid(b))["request_id"]
    r2 = send_ok(c, e, uid(d))["request_id"]
    results = race([(r1, uid(b)), (r2, uid(d))])
    assert sorted(results) == ["group_limit_reached", "ok"], results
    assert len(db.exec(select(Group).where(Group.event_id == e)).all()) == 1


def test_two_new_groups_for_one_user(login_as, race, db):
    """x (limit 1) sent two user requests; both targets accept at once: only one new group."""
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, x = users(login_as, 3)
    e = make_event(host, max_groups_per_user=1)
    for u in (a, b, x):
        join(u, e)
    r1 = send_ok(x, e, uid(a))["request_id"]
    r2 = send_ok(x, e, uid(b))["request_id"]
    results = race([(r1, uid(a)), (r2, uid(b))])
    assert sorted(results) == ["group_limit_per_user", "ok"], results
    assert len(db.exec(select(GroupMember).where(GroupMember.user_id == uid(x))).all()) == 1


def test_same_request_accepted_twice_at_once(login_as, race, db):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b, c = users(login_as, 3)
    e = make_event(host)
    for u in (a, b, c):
        join(u, e)
    gid = form_group(a, b, e)
    rid = send_ok(c, e, gid, "group")["request_id"]
    results = race([(rid, uid(a)), (rid, uid(b))])
    assert sorted(results) == ["ok", "request_not_pending"], results
    assert members(db, gid) == {uid(a), uid(b), uid(c)}


@pytest.mark.parametrize("limit", [1, 2])
def test_crossing_structured_accepts_at_once(login_as, race, db, limit):
    """a and b requested each other and each accepts the other's request at the same moment:
    one group, both requests accepted with it."""
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b = users(login_as, 2)
    e = make_event(host, max_groups_per_user=limit)
    join(a, e)
    join(b, e)
    r1 = send_ok(a, e, uid(b))["request_id"]
    r2 = send_ok(b, e, uid(a))["request_id"]
    results = race([(r1, uid(b)), (r2, uid(a))])
    assert sorted(results) == ["ok", "request_not_pending"], results
    groups = db.exec(select(Group).where(Group.event_id == e)).all()
    assert len(groups) == 1 and members(db, groups[0].id) == {uid(a), uid(b)}
    for rid in (r1, r2):
        stored = db.get(Request, rid)
        assert (stored.status, stored.group_id) == ("accepted", groups[0].id)


@pytest.mark.parametrize("limit", [1, 2])
def test_request_sent_while_the_pair_forms_a_group(login_as, monkeypatch, db, limit):
    """b sends a crossing request while accepting a's. Whatever the interleaving, the pair ends
    in one group and no request is left stuck as pending."""
    slow_down(monkeypatch, "_add_member")
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b = users(login_as, 2)
    e = make_event(host, max_groups_per_user=limit)
    join(a, e)
    join(b, e)
    r1 = send_ok(a, e, uid(b))["request_id"]
    results = at_once([
        (uid(b), lambda s, u: svc.accept_request(s, r1, u)),
        (uid(b), lambda s, u: svc.create_request(
            s, u, event_id=e, target_type="user", target_id=uid(a), message=None)),
    ])
    assert results[0] == "ok" and results[1] in ("ok", "already_in_group"), results
    for r in db.exec(select(Request).where(Request.event_id == e, Request.status == "pending")).all():
        assert a.post(f"/api/requests/{r.id}/accept").status_code == 200
    db.expire_all()
    groups = db.exec(select(Group).where(Group.event_id == e)).all()
    assert len(groups) == 1 and members(db, groups[0].id) == {uid(a), uid(b)}
    for r in db.exec(select(Request).where(Request.event_id == e)).all():
        assert (r.status, r.group_id) == ("accepted", groups[0].id)


# --- informal events: one connection per pair ----------------------------------------------------

def informal_pair(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    a, b = users(login_as, 2)
    e = make_event(host, type="informal")
    join(a, e)
    join(b, e)
    return a, b, e


def send_call(event_id: str, target_id: str):
    return lambda s, u: svc.create_request(
        s, u, event_id=event_id, target_type="user", target_id=target_id, message=None
    )


def assert_one_connection_for_all(db, e, request_ids) -> None:
    db.expire_all()
    cons = db.exec(select(Connection).where(Connection.event_id == e)).all()
    assert len(cons) == 1
    for rid in request_ids:
        stored = db.get(Request, rid)
        assert (stored.status, stored.connection_id) == ("accepted", cons[0].id)


def test_crossing_informal_accepts_at_once(login_as, monkeypatch, db):
    """a and b requested each other and each accepts the other's request at the same moment."""
    slow_down(monkeypatch, "_connection_between")
    a, b, e = informal_pair(login_as)
    r1 = send_ok(a, e, uid(b))["request_id"]
    r2 = send_ok(b, e, uid(a))["request_id"]
    results = at_once([
        (uid(b), lambda s, u: svc.accept_request(s, r1, u)),
        (uid(a), lambda s, u: svc.accept_request(s, r2, u)),
    ])
    assert sorted(results) == ["ok", "request_not_pending"], results
    assert_one_connection_for_all(db, e, [r1, r2])


def test_informal_requests_sent_at_once(login_as, monkeypatch, db):
    """A double-click sends one request; both users requesting each other at once leaves two
    crossing requests, and accepting either resolves both."""
    slow_down(monkeypatch, "create_thread")
    a, b, e = informal_pair(login_as)
    results = at_once([
        (uid(a), send_call(e, uid(b))),
        (uid(a), send_call(e, uid(b))),
        (uid(b), send_call(e, uid(a))),
    ])
    assert sorted(results) == ["duplicate_request", "ok", "ok"], results
    pending = db.exec(select(Request).where(Request.event_id == e, Request.status == "pending")).all()
    assert {(r.sender_id, r.target_user_id) for r in pending} == {(uid(a), uid(b)), (uid(b), uid(a))}
    incoming = next(r for r in pending if r.target_user_id == uid(b))
    assert b.post(f"/api/requests/{incoming.id}/accept").status_code == 200
    assert_one_connection_for_all(db, e, [r.id for r in pending])


def test_request_sent_while_the_pair_connects(login_as, monkeypatch, db):
    """b sends a crossing request while accepting a's. Whatever the interleaving, the pair ends
    with one connection and no request left stuck as pending."""
    slow_down(monkeypatch, "_connection_between")
    a, b, e = informal_pair(login_as)
    r1 = send_ok(a, e, uid(b))["request_id"]
    results = at_once([
        (uid(b), lambda s, u: svc.accept_request(s, r1, u)),
        (uid(b), send_call(e, uid(a))),
    ])
    assert results[0] == "ok" and results[1] in ("ok", "already_connected"), results
    for r in db.exec(select(Request).where(Request.event_id == e, Request.status == "pending")).all():
        assert a.post(f"/api/requests/{r.id}/accept").status_code == 200
    all_ids = db.exec(select(Request.id).where(Request.event_id == e)).all()
    assert_one_connection_for_all(db, e, all_ids)
