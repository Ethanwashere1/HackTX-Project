"""Group limits hold when accepts race: real threads, each with its own DB session and transaction.

Each test widens the window between the limit checks and the write (a sleep before the member row
is added), so without the row locks both accepts would pass their checks and the limit would break.
"""

import threading
import time

import pytest
from sqlmodel import Session, select

from app import db as dbmod
from app.errors import AppError
from app.models import Group, GroupMember, User
from app.services import requests as svc
from tests.test_requests import form_group, join, make_event, members, send_ok, uid


@pytest.fixture
def race(monkeypatch):
    real_add = svc._add_member

    def slow_add(db, group, user_id):
        time.sleep(0.3)
        real_add(db, group, user_id)

    monkeypatch.setattr(svc, "_add_member", slow_add)

    def _race(attempts: list[tuple[str, str]]) -> list[str]:
        """Run accept_request(request_id, by user_id) for all attempts at once.
        Returns each attempt's outcome: "ok" or the error code."""
        barrier = threading.Barrier(len(attempts))
        results: list[str | None] = [None] * len(attempts)

        def run(i: int, request_id: str, user_id: str) -> None:
            with Session(dbmod.get_engine()) as s:
                user = s.get(User, user_id)
                barrier.wait()
                try:
                    svc.accept_request(s, request_id, user)
                    results[i] = "ok"
                except AppError as exc:
                    results[i] = exc.code
                except Exception as exc:  # noqa: BLE001 - surfaced in the assertion
                    results[i] = repr(exc)

        threads = [threading.Thread(target=run, args=(i, *a)) for i, a in enumerate(attempts)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert all(not t.is_alive() for t in threads), "accept deadlocked"
        return results

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
