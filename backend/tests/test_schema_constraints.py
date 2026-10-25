"""Database-level invariants from migration 0001 (Alembic's model diff doesn't cover these)."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.ids import new_id


@pytest.fixture
def ids(db):
    """Two users, a structured event and a group in it; returns their ids."""
    u1, u2, evt, grp = new_id("usr"), new_id("usr"), new_id("evt"), new_id("grp")
    db.execute(text(
        "INSERT INTO users (id, email, name, created_at, updated_at) VALUES "
        "(:u1, 'a@x.com', 'A', now(), now()), (:u2, 'b@x.com', 'B', now(), now())"
    ), {"u1": u1, "u2": u2})
    db.execute(text(
        "INSERT INTO events (id, host_id, name, description, type, tone, group_count, min_size,"
        " max_size, required_fields, interview_enabled, created_at)"
        " VALUES (:e, :u1, 'E', '', 'structured', 'casual', 2, 2, 4, '[]', false, now())"
    ), {"e": evt, "u1": u1})
    db.execute(text("INSERT INTO groups (id, event_id, name, created_at) VALUES (:g, :e, 'G', now())"),
               {"g": grp, "e": evt})
    db.commit()
    return {"u1": u1, "u2": u2, "evt": evt, "grp": grp}


def insert_event(db, ids, **cols):
    base = {"id": new_id("evt"), "host_id": ids["u1"], "name": "E", "description": "",
            "type": "structured", "tone": "casual", "group_count": 2, "min_size": 2,
            "max_size": 4, "max_groups_per_user": 1, "required_fields": "[]",
            "interview_enabled": False}
    base.update(cols)
    names = ", ".join(base)
    values = ", ".join(f":{k}" for k in base)
    db.execute(text(f"INSERT INTO events ({names}, created_at) VALUES ({values}, now())"), base)
    db.commit()


def assert_rejected(db, fn):
    with pytest.raises(IntegrityError):
        fn()
    db.rollback()


def test_structured_event_gets_max_groups_per_user_default(db, ids):
    assert db.execute(text("SELECT max_groups_per_user FROM events WHERE id = :e"),
                      {"e": ids["evt"]}).scalar() == 1


@pytest.mark.parametrize(
    "cols",
    [
        {"type": "hybrid"},
        {"tone": "formal"},
        {"min_size": 5, "max_size": 4},
        {"group_count": 0},
        {"min_size": 0},
        {"max_groups_per_user": 0},
        {"group_count": None},
        {"max_groups_per_user": None},
        {"type": "informal"},  # informal with group settings
    ],
)
def test_event_check_constraints(db, ids, cols):
    assert_rejected(db, lambda: insert_event(db, ids, **cols))


def test_informal_event_without_group_settings_is_allowed(db, ids):
    insert_event(db, ids, type="informal", group_count=None, min_size=None, max_size=None,
                 max_groups_per_user=None)


def insert_request(db, ids, **cols):
    base = {"id": new_id("req"), "event_id": ids["evt"], "sender_id": ids["u1"],
            "target_type": "user", "target_user_id": ids["u2"], "target_group_id": None,
            "status": "pending"}
    base.update(cols)
    names = ", ".join(base)
    values = ", ".join(f":{k}" for k in base)
    db.execute(text(f"INSERT INTO requests ({names}, created_at) VALUES ({values}, now())"), base)
    db.commit()


@pytest.mark.parametrize("cols", [{"status": "maybe"}, {"target_type": "team"}])
def test_request_enums(db, ids, cols):
    assert_rejected(db, lambda: insert_request(db, ids, **cols))


def test_one_pending_request_per_user_target(db, ids):
    insert_request(db, ids)
    assert_rejected(db, lambda: insert_request(db, ids))
    # Once decided, a new pending request is allowed again.
    db.execute(text("UPDATE requests SET status = 'declined'"))
    db.commit()
    insert_request(db, ids)


def test_one_pending_request_per_group_target(db, ids):
    group = {"target_type": "group", "target_user_id": None, "target_group_id": ids["grp"]}
    insert_request(db, ids, **group)
    assert_rejected(db, lambda: insert_request(db, ids, **group))
    insert_request(db, ids, **group, status="cancelled")


def insert_org_member(db, ids, role, status):
    org = new_id("org")
    db.execute(text("INSERT INTO orgs (id, name, verification, email_domains, created_at)"
                    " VALUES (:o, 'O', 'manual', '[]', now())"), {"o": org})
    db.execute(text("INSERT INTO org_members (id, org_id, user_id, role, status, requested_at)"
                    " VALUES (:id, :o, :u, :r, :s, now())"),
               {"id": new_id("om"), "o": org, "u": ids["u1"], "r": role, "s": status})
    db.commit()
    return org


@pytest.mark.parametrize(
    "role,status", [("owner", "approved"), ("member", "banned"), ("admin", "pending"),
                    ("admin", "declined")],
)
def test_org_member_constraints(db, ids, role, status):
    assert_rejected(db, lambda: insert_org_member(db, ids, role, status))


def test_orgs_are_discoverable_by_default(db, ids):
    org = insert_org_member(db, ids, "admin", "approved")
    assert db.execute(text("SELECT discoverable FROM orgs WHERE id = :o"), {"o": org}).scalar() is True


def test_group_member_event_must_match_group(db, ids):
    other = new_id("evt")
    insert_event(db, ids, id=other)

    def add(event_id):
        db.execute(text("INSERT INTO group_members (id, group_id, event_id, user_id, joined_at)"
                        " VALUES (:id, :g, :e, :u, now())"),
                   {"id": new_id("gm"), "g": ids["grp"], "e": event_id, "u": ids["u2"]})
        db.commit()

    assert_rejected(db, lambda: add(other))
    add(ids["evt"])


def test_profile_requires_event_membership(db, ids):
    def add_profile():
        db.execute(text("INSERT INTO profiles (id, event_id, user_id, traits, transcript,"
                        " profile_text, updated_at) VALUES (:id, :e, :u, '{}', '[]', '', now())"),
                   {"id": new_id("prf"), "e": ids["evt"], "u": ids["u2"]})
        db.commit()

    assert_rejected(db, add_profile)
    db.execute(text("INSERT INTO event_members (id, event_id, user_id, answers, fields, socials,"
                    " joined_at) VALUES (:id, :e, :u, '{}', '{}', '[]', now())"),
               {"id": new_id("em"), "e": ids["evt"], "u": ids["u2"]})
    db.commit()
    add_profile()


def test_lookup_indexes_exist(db):
    insp = inspect(db.connection())
    assert "ix_messages_sender_id" in {i["name"] for i in insp.get_indexes("messages")}
    assert "ix_requests_decided_by" in {i["name"] for i in insp.get_indexes("requests")}
