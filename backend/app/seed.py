"""Demo seed data: `uv run python -m app.seed [--reset | --wipe] [--fake-embeddings]`.

Creates the "UT Austin" org with a structured event ("HackTX team-up") and an informal one
("Study buddies"), 15 profiled participants plus a host, a few groups, requests and a connection,
then embeds every seed member so recommendations work.

- Seed data is everything owned by a user whose email ends in @seed.squadup.dev: those users, the
  orgs they created and the events they host (with everything inside them, including memberships
  that real users added during a demo). Real users' accounts, profiles and contacts are never
  touched, and neither is anything outside the seed orgs and events.
- Running it again doesn't duplicate anything: each step looks for what it would create first.
  `--reset` wipes the seed data and seeds again (the demo reset); `--wipe` only wipes.
- Members, groups and requests go through the same service functions as the API, so profile_text
  is built the normal way. Embeddings use Gemini (embed_members, then the Snowflake sync) when
  GEMINI_API_KEY is configured; otherwise, with --fake-embeddings, or if Gemini fails, each
  profile_text gets a deterministic local vector (hashed bag of words) so similarity still works.
"""

import argparse
import hashlib
import logging
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect, null
from sqlmodel import Session, delete, or_, select

from app import db as dbmod
from app.config import BACKEND_DIR, EMBEDDING_DIM, get_settings
from app.models import (
    ContactMethod,
    Event,
    EventMember,
    Group,
    Message,
    Org,
    OrgMember,
    Question,
    Request,
    User,
)
from app.models.base import utcnow
from app.services import embeddings, snowflake_store
from app.services import requests as request_svc
from app.services.events import (
    event_questions,
    get_membership,
    share_url,
    validate_answers,
    validate_fields,
)
from app.services.groups import user_group_ids
from app.services.profiles import get_or_create_profile, merge_socials, rebuild_member_texts
from app.services.users import list_contacts, upsert_user

log = logging.getLogger("app.seed")

SEED_DOMAIN = "seed.squadup.dev"
ORG_NAME = "UT Austin"
HOST_KEY = "morgan"


def seed_email(key: str) -> str:
    return f"{key}@{SEED_DOMAIN}"


# --- seed data -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Person:
    key: str  # email local part
    name: str
    role: str  # HackTX question 1
    skills: list[str]
    level: str
    idea: str  # HackTX question 2
    tracks: list[str]  # HackTX question 3
    summary: str  # as if from the interview Summarizer
    social_notes: str | None = None  # as if from the SerpAPI lookup
    socials: list[dict[str, str]] = field(default_factory=list)
    phone: str | None = None
    # Study buddies: (major, courses, study style, availability); None = not in that event.
    study: tuple[str, list[str], str, str] | None = None


HOST = Person(
    key=HOST_KEY, name="Morgan Reyes", role="Product / pitch", skills=[], level="advanced",
    idea="", tracks=[], summary="HackTX organizer and UT Austin org admin.",
)

PEOPLE = [
    Person(
        "ana", "Ana Ruiz", "Frontend", ["React", "TypeScript", "Tailwind", "Figma"], "intermediate",
        "An accessible campus map that routes around construction and broken elevators",
        ["Education", "Social good"],
        "Frontend developer who loves polished, accessible UI. Has shipped two React apps at past "
        "hackathons and wants a backend teammate so she can focus on the interface.",
        "GitHub: 31 public repos, mostly TypeScript and React; pinned project longhorn-map, an "
        "accessible campus map.",
        [{"kind": "github", "value": "ana-ruiz-dev"}], "+1 512-555-0101",
        ("Computer Science", ["CS 314 Data Structures", "CS 429 Computer Organization"],
         "Talk through problems", "Weekday evenings after 6pm"),
    ),
    Person(
        "ben", "Ben Li", "Backend", ["Python", "FastAPI", "PostgreSQL", "Docker"], "advanced",
        "A real-time API for Capital Metro bus arrivals with crowding predictions",
        ["Sustainability", "Social good"],
        "Backend engineer focused on APIs and databases. Interned on a data platform team, likes "
        "clean schemas and fast endpoints, and wants to ship a full working demo.",
        "GitHub: 18 repos in Python and Go; contributor to a FastAPI extension.",
        [{"kind": "github", "value": "benli-api"}], "+1 512-555-0102",
        ("Computer Science", ["CS 439 Operating Systems", "CS 331 Algorithms"],
         "Practice problems together", "Tuesday and Thursday afternoons"),
    ),
    Person(
        "cara", "Cara Okafor", "Design", ["Figma", "UX research", "Illustration", "Prototyping"],
        "intermediate",
        "A friendly app that helps first-year students find clubs and study spots",
        ["Education", "Social good"],
        "Product designer who runs quick user interviews and turns them into clickable Figma "
        "prototypes. Wants to make the demo look and feel great.",
        "Portfolio on Behance with UX case studies for two student apps.",
        [{"kind": "instagram", "value": "@cara.draws"}], "+1 512-555-0103",
        ("Design", ["SDS 321 Probability"], "Quiet co-working", "Weekend mornings"),
    ),
    Person(
        "dev", "Dev Patel", "ML / AI", ["Python", "PyTorch", "LLMs", "RAG", "LangChain"], "advanced",
        "An LLM triage assistant that helps clinic patients describe symptoms before a visit",
        ["AI/ML", "Health"],
        "Machine learning engineer who builds LLM and retrieval (RAG) pipelines in Python. Did NLP "
        "research on clinical notes and wants to build an AI health tool.",
        "GitHub: maintains a small open-source RAG evaluation library in Python.",
        [{"kind": "github", "value": "devpatel-ml"}], "+1 512-555-0104",
    ),
    Person(
        "eli", "Eli Nguyen", "ML / AI", ["Python", "Computer vision", "OpenCV", "TensorFlow"],
        "intermediate",
        "A computer vision app that sorts recycling from a phone photo",
        ["AI/ML", "Sustainability", "Health"],
        "ML student focused on computer vision and model training in Python. Wants to pair with "
        "someone strong on LLMs and ship an AI demo.",
        None, [{"kind": "linkedin", "value": "eli-nguyen-ml"}], "+1 512-555-0105",
        ("Computer Science", ["M 340L Matrices", "SDS 321 Probability"],
         "Practice problems together", "Weekday evenings"),
    ),
    Person(
        "fatima", "Fatima Hassan", "Full-stack", ["Next.js", "TypeScript", "Supabase", "Stripe"],
        "advanced",
        "A budgeting app that splits rent and bills between roommates",
        ["Fintech"],
        "Full-stack developer who ships quickly with Next.js and Supabase. Has built payment flows "
        "with Stripe and enjoys fintech problems.",
        "GitHub: 24 repos, mostly Next.js and TypeScript; built a Stripe billing starter.",
        [{"kind": "github", "value": "fatima-builds"}], "+1 512-555-0106",
    ),
    Person(
        "gabe", "Gabe Romero", "Hardware", ["Arduino", "Raspberry Pi", "C++", "3D printing"],
        "intermediate",
        "Low-cost air quality sensors for East Austin neighborhoods",
        ["Hardware", "Sustainability"],
        "Hardware hacker who builds IoT sensors with Arduino and Raspberry Pi. Brings his own "
        "soldering kit and wants a team that can visualize the sensor data.",
        None, [{"kind": "instagram", "value": "@gabe.makes"}], "+1 512-555-0107",
    ),
    Person(
        "hiro", "Hiro Tanaka", "Backend", ["Go", "Kubernetes", "AWS", "Redis"], "advanced",
        "A fraud alert service that flags unusual card transactions in real time",
        ["Fintech"],
        "Backend and infrastructure engineer who likes distributed systems, Go and cloud "
        "deployment. Happy to own deployment and DevOps for the team.",
        "GitHub: Go projects including a Kubernetes operator with 200 stars.",
        [{"kind": "github", "value": "hiro-tanaka"}], "+1 512-555-0108",
        ("Computer Science", ["CS 439 Operating Systems", "CS 429 Computer Organization"],
         "Practice problems together", "Tuesday and Thursday afternoons"),
    ),
    Person(
        "isla", "Isla Brooks", "Product / pitch",
        ["Product management", "Pitching", "Notion", "Market research"], "beginner",
        "Anything that helps nonprofits recruit and schedule volunteers",
        ["Social good", "Education"],
        "Business student who is great at pitching and keeping a team on scope. First hackathon; "
        "wants to own the demo story and the slides.",
        "LinkedIn: President of a campus volunteering nonprofit.",
        [{"kind": "linkedin", "value": "isla-brooks"}], "+1 512-555-0109",
    ),
    Person(
        "jordan", "Jordan Kim", "Full-stack", ["Vue", "Node.js", "Firebase", "JavaScript"],
        "beginner",
        "A study group finder that matches classmates by course and schedule",
        ["Education"],
        "Second-year CS student who has built small web apps with Vue and Firebase. Eager to learn "
        "from experienced teammates and work on an education app.",
        None, [{"kind": "github", "value": "jordankim-dev"}], "+1 512-555-0110",
        ("Computer Science", ["CS 314 Data Structures", "M 340L Matrices"],
         "Teach each other", "Most evenings"),
    ),
    Person(
        "kai", "Kai Johnson", "Game dev", ["Unity", "C#", "Blender", "Game design"], "intermediate",
        "A co-op browser game that teaches climate science",
        ["Gaming", "Education"],
        "Game developer who prototypes fast in Unity and C#. Loves game jams and wants to make "
        "something playful.",
        "itch.io: five game jam entries, two ranked in the top 10%.",
        [{"kind": "instagram", "value": "@kai.games"}], "+1 512-555-0111",
    ),
    Person(
        "liam", "Liam O'Brien", "Data", ["Python", "pandas", "SQL", "Tableau", "Data visualization"],
        "intermediate",
        "A dashboard that maps Austin heat islands and tree cover",
        ["Sustainability", "Social good"],
        "Data science student who cleans messy public datasets and tells stories with charts. "
        "Wants to build a data visualization for climate or city data.",
        None, [{"kind": "linkedin", "value": "liam-obrien-data"}], "+1 512-555-0112",
        ("Statistics and Data Science", ["SDS 321 Probability", "M 340L Matrices"],
         "Quiet co-working", "Weekend afternoons"),
    ),
    Person(
        "mia", "Mia Garcia", "Mobile", ["Swift", "SwiftUI", "Kotlin", "Flutter"], "advanced",
        "A mobile app that reminds students to take medication and tracks refills",
        ["Health"],
        "Mobile developer with an iOS app on the App Store. Builds polished SwiftUI and Flutter "
        "apps and is interested in health tech.",
        "GitHub: SwiftUI component library; App Store app with 4.8 stars.",
        [{"kind": "github", "value": "mia-mobile"}], "+1 512-555-0113",
        ("Computer Science", ["CS 331 Algorithms", "CS 314 Data Structures"],
         "Talk through problems", "Monday and Wednesday evenings"),
    ),
    Person(
        "noah", "Noah Williams", "Security", ["Rust", "Cryptography", "Reverse engineering", "Linux"],
        "advanced",
        "A privacy-first password sharing tool for families",
        ["Fintech", "Social good"],
        "Security-minded systems programmer who writes Rust and plays CTFs. Wants to build "
        "something private and secure.",
        "CTFtime: captain of a university CTF team.",
        [{"kind": "github", "value": "noah-rs"}], "+1 512-555-0114",
        ("Computer Science", ["CS 439 Operating Systems", "CS 331 Algorithms"],
         "Quiet co-working", "Late nights"),
    ),
    Person(
        "priya", "Priya Sharma", "ML / AI", ["Python", "NLP", "Hugging Face", "LLMs"], "intermediate",
        "An AI study coach that turns lecture notes into quizzes and explains wrong answers",
        ["AI/ML", "Education"],
        "ML student who fine-tunes NLP models with Hugging Face and Python. Wants to build an "
        "LLM-powered education tool with a strong teammate on the frontend.",
        "GitHub: notebooks on fine-tuning LLMs for question generation.",
        [{"kind": "github", "value": "priya-nlp"}], "+1 512-555-0115",
        ("Computer Science", ["CS 314 Data Structures", "SDS 321 Probability"],
         "Teach each other", "Weekday evenings"),
    ),
]

HACKTX = {
    "name": "HackTX team-up",
    "description": "Find your HackTX 2026 team: 6 teams of 3-4. Answer three quick questions and "
                   "SquadUp suggests people and teams that fit.",
    "type": "structured",
    "tone": "casual",
    "group_count": 6,
    "min_size": 3,
    "max_size": 4,
    "max_groups_per_user": 1,
    "required_fields": ["skills", "experience_level"],
    "interview_enabled": True,
    "questions": [
        {"text": "What role do you want on the team?", "kind": "single_choice", "required": True,
         "options": ["Frontend", "Backend", "Full-stack", "ML / AI", "Design", "Hardware", "Mobile",
                     "Data", "Security", "Game dev", "Product / pitch"]},
        {"text": "What do you want to build this weekend?", "kind": "text", "required": True},
        {"text": "Which tracks interest you?", "kind": "multi_choice", "required": False,
         "options": ["AI/ML", "Health", "Sustainability", "Fintech", "Education", "Social good",
                     "Gaming", "Hardware"]},
    ],
}

STUDY = {
    "name": "Study buddies",
    "description": "Find a study partner for this semester's CS, math and stats courses.",
    "type": "informal",
    "tone": "professional",
    "required_fields": ["major"],
    "interview_enabled": False,
    "questions": [
        {"text": "Which courses are you studying for?", "kind": "multi_choice", "required": True,
         "options": ["CS 314 Data Structures", "CS 429 Computer Organization",
                     "CS 439 Operating Systems", "CS 331 Algorithms", "M 340L Matrices",
                     "SDS 321 Probability"]},
        {"text": "How do you like to study?", "kind": "single_choice", "required": True,
         "options": ["Quiet co-working", "Talk through problems", "Practice problems together",
                     "Teach each other"]},
        {"text": "When are you usually free to study?", "kind": "text", "required": False},
    ],
}

# HackTX groups (name, members). The first two form the group by request; the rest join it.
HACKTX_GROUPS = [
    ("Team Pixel", ["ana", "ben", "cara"]),  # open, 3 of 4
    ("Team Neural", ["dev", "eli"]),  # open, 2 of 4
    ("Team Volt", ["gabe", "hiro", "fatima", "isla"]),  # full
]
# (event, sender, target user key or group name, outcome, message)
REQUESTS = [
    ("hacktx", "jordan", "Team Pixel", "pending", "I can help with the Vue and Node side!"),
    ("hacktx", "mia", "noah", "pending", "Want to build a secure health app together?"),
    ("hacktx", "kai", "liam", "declined", "Want to make a climate game with real data?"),
    ("study", "ben", "hiro", "accepted", "Want to review CS 439 together?"),
    ("study", "jordan", "ana", "pending", "Study CS 314 together this week?"),
    ("study", "noah", "mia", "declined", "Up for CS 331 practice problems?"),
]
TEAM_PIXEL_CHAT = [
    ("ana", "Welcome Cara! I'll start on the map UI tonight."),
    ("ben", "API skeleton is up, I'll share the repo link here soon."),
    ("cara", "Sketching the onboarding flow in Figma now."),
]
# Printed after seeding: (key, what to show).
LOGINS = [
    ("priya", "solo in HackTX: ranked people and open groups (Team Neural should lead)"),
    ("jordan", "pending request to Team Pixel, so it's excluded; Study buddies has a pending request too"),
    ("ana", "in Team Pixel: team page and chat; no group recommendations (max_groups_per_user=1)"),
    ("ben", "Study buddies: connected with Hiro (informal 1:1 connection)"),
    (HOST_KEY, "org admin and host of both events"),
]


# --- fake embeddings -----------------------------------------------------------------------------

_STOPWORDS = frozenset(
    """a about after all also an and any are as at be before being but by can do for from get has
    have he her his i i'm in into is it its just like me more most my no not of on one or our out
    over she so some someone something than that the their them then there they this to two up us
    want wants was we were what when where who will with would you your""".split()
)
# Lines every member shares (event header, question texts) or that only hold handles.
_SKIP_LINE = re.compile(r"^(Event|Q|Socials):")
_LABEL = re.compile(r"^[A-Za-z ]{1,40}:\s*")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*")


def fake_embedding(text: str) -> list[float] | None:
    """A deterministic unit-length 768-dim vector: a hashed bag of the text's words.

    Skips the lines all members share and the field labels, so the similarity of two members
    reflects their own answers, skills and summaries. None when there is nothing to embed."""
    counts: Counter[str] = Counter()
    for line in (text or "").splitlines():
        if _SKIP_LINE.match(line):
            continue
        for token in _TOKEN.findall(_LABEL.sub("", line, count=1).lower()):
            token = token.rstrip(".")
            if len(token) >= 2 and token not in _STOPWORDS:
                counts[token] += 1
    vector = [0.0] * EMBEDDING_DIM
    for token, n in counts.items():
        digest = hashlib.blake2b(token.encode(), digest_size=4).digest()
        vector[int.from_bytes(digest, "big") % EMBEDDING_DIM] += 1 + math.log(n)
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return None
    return [v / norm for v in vector]


# --- wipe ----------------------------------------------------------------------------------------

def seed_user_ids(db: Session) -> list[str]:
    """Seed users: the seed email domain, and never signed in with Google."""
    return list(
        db.exec(
            select(User.id).where(
                User.email.endswith("@" + SEED_DOMAIN, autoescape=True), User.google_sub.is_(None)
            )
        ).all()
    )


def wipe(db: Session) -> dict[str, int]:
    """Delete the seed users, the orgs they created and the events they host, with everything
    inside those (FK cascades). Also removes those events' vectors from Snowflake. Commits."""
    user_ids = seed_user_ids(db)
    if not user_ids:
        return {"users": 0, "orgs": 0, "events": 0}
    org_ids = list(db.exec(select(Org.id).where(Org.created_by.in_(user_ids))).all())
    event_ids = list(
        db.exec(
            select(Event.id).where(or_(Event.host_id.in_(user_ids), Event.org_id.in_(org_ids)))
        ).all()
    )
    if org_ids:
        db.exec(delete(Org).where(Org.id.in_(org_ids)))
    db.exec(delete(User).where(User.id.in_(user_ids)))
    db.commit()
    if event_ids and get_settings().snowflake_configured:
        try:
            snowflake_store.delete_events(event_ids)
        except snowflake_store.SnowflakeError as exc:
            log.warning("Could not remove the seed events' vectors from Snowflake: %s", exc)
    return {"users": len(user_ids), "orgs": len(org_ids), "events": len(event_ids)}


# --- seed ----------------------------------------------------------------------------------------

@dataclass
class SeedResult:
    org_id: str
    events: dict[str, str]  # hacktx|study -> event_id
    users: dict[str, str]  # person key -> user_id
    groups: dict[str, str]  # group name -> group_id
    embedded_with: str  # gemini|fake
    member_ids: list[str]


def _upsert_people(db: Session) -> dict[str, User]:
    users = {}
    for p in [HOST, *PEOPLE]:
        user = upsert_user(db, email=seed_email(p.key), name=p.name)
        profile = get_or_create_profile(db, user.id, lock=True)
        if (profile.summary, profile.social_notes) != (p.summary, p.social_notes):
            profile.summary, profile.social_notes = p.summary, p.social_notes
            profile.updated_at = utcnow()
            db.add(profile)
        contacts = [{"kind": "discord", "value": f"{p.key}.squadup"}]
        if p.phone:
            contacts.append({"kind": "phone", "value": p.phone})
        if list_contacts(db, user.id) != contacts:
            db.exec(delete(ContactMethod).where(ContactMethod.user_id == user.id))
            for i, c in enumerate(contacts):
                db.add(ContactMethod(user_id=user.id, kind=c["kind"], value=c["value"], position=i))
        db.commit()
        users[p.key] = user
    return users


def _ensure_org(db: Session, users: dict[str, User]) -> Org:
    admin_id = users[HOST_KEY].id
    org = db.exec(select(Org).where(Org.created_by == admin_id, Org.name == ORG_NAME)).first()
    if org is None:
        org = Org(name=ORG_NAME, verification="email_domain", email_domains=["utexas.edu"],
                  discoverable=True, created_by=admin_id)
        db.add(org)
        db.flush()
    for key, user in users.items():
        exists = db.exec(
            select(OrgMember.id).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id)
        ).first()
        if exists is None:
            db.add(OrgMember(
                org_id=org.id, user_id=user.id, role="admin" if key == HOST_KEY else "member",
                status="approved", decided_at=utcnow(), decided_by=admin_id,
            ))
    db.commit()
    return org


def _ensure_event(db: Session, org: Org, host: User, spec: dict[str, Any]) -> Event:
    """Like POST /api/events, unless the host already has an event with this name in the org."""
    event = db.exec(
        select(Event).where(Event.org_id == org.id, Event.host_id == host.id, Event.name == spec["name"])
    ).first()
    if event is not None:
        return event
    structured = spec["type"] == "structured"
    event = Event(
        org_id=org.id, host_id=host.id, name=spec["name"], description=spec["description"],
        type=spec["type"], tone=spec["tone"],
        group_count=spec.get("group_count"), min_size=spec.get("min_size"),
        max_size=spec.get("max_size"),
        # Explicit NULL for informal events, as the router does.
        max_groups_per_user=spec["max_groups_per_user"] if structured else null(),
        required_fields=spec["required_fields"], interview_enabled=spec["interview_enabled"],
    )
    db.add(event)
    db.flush()
    for i, q in enumerate(spec["questions"]):
        db.add(Question(event_id=event.id, position=i, text=q["text"], kind=q["kind"],
                        options=q.get("options"), required=q["required"]))
    db.commit()
    db.refresh(event)
    return event


def _join(db: Session, event: Event, user: User, values: list[Any], fields: dict[str, Any],
          socials: list[dict[str, str]]) -> None:
    """Like POST /api/events/{id}/join (validation, socials merge); skipped if already a member.
    Match texts are rebuilt for everyone at the end."""
    if get_membership(db, event.id, user.id) is not None:
        return
    questions = event_questions(db, event.id)
    answers = validate_answers(questions, [(q.id, v) for q, v in zip(questions, values)])
    fields = validate_fields(event.required_fields, fields)
    profile = get_or_create_profile(db, user.id, lock=True)
    merged = merge_socials(profile.socials, socials)
    if merged != profile.socials:
        profile.socials = merged
        profile.updated_at = utcnow()
        db.add(profile)
    db.add(EventMember(event_id=event.id, user_id=user.id, answers=answers, fields=fields))
    db.commit()


def _group_of(db: Session, event_id: str, user_id: str) -> str | None:
    ids = user_group_ids(db, user_id, event_id)
    return ids[0] if ids else None


def _ensure_group(db: Session, event: Event, users: dict[str, User], name: str, keys: list[str]) -> str:
    """Form the group by request + accept, then add the other members the same way."""
    first, second = users[keys[0]], users[keys[1]]
    group_id = _group_of(db, event.id, first.id)
    if group_id is None:
        req = request_svc.create_request(db, first, event_id=event.id, target_type="user",
                                         target_id=second.id, message="Want to team up?")
        group_id = request_svc.accept_request(db, req.id, second).group_id
    for key in keys[2:]:
        if _group_of(db, event.id, users[key].id) is None:
            req = request_svc.create_request(db, users[key], event_id=event.id, target_type="group",
                                             target_id=group_id, message="Can I join your team?")
            request_svc.accept_request(db, req.id, first)
    group = db.get(Group, group_id)
    if group.name != name:
        group.name = name
        db.add(group)
        db.commit()
    return group_id


def _ensure_request(db: Session, event: Event, users: dict[str, User], groups: dict[str, str],
                    sender_key: str, target: str, outcome: str, message: str) -> None:
    sender = users[sender_key]
    if target in groups:
        target_type, target_id = "group", groups[target]
        decider = users[next(keys for name, keys in HACKTX_GROUPS if name == target)[0]]
        column = Request.target_group_id
    else:
        target_type, target_id, decider = "user", users[target].id, users[target]
        column = Request.target_user_id
    exists = db.exec(
        select(Request.id).where(Request.event_id == event.id, Request.sender_id == sender.id,
                                 column == target_id)
    ).first()
    if exists is not None:
        return
    req = request_svc.create_request(db, sender, event_id=event.id, target_type=target_type,
                                     target_id=target_id, message=message)
    if outcome == "accepted":
        request_svc.accept_request(db, req.id, decider)
    elif outcome == "declined":
        request_svc.decline_request(db, req.id, decider)


def _ensure_chat(db: Session, group_id: str, users: dict[str, User]) -> None:
    group = db.get(Group, group_id)
    if group.thread_id is None or db.exec(
        select(Message.id).where(Message.thread_id == group.thread_id)
    ).first() is not None:
        return
    for key, text in TEAM_PIXEL_CHAT:
        db.add(Message(thread_id=group.thread_id, sender_id=users[key].id, text=text))
        db.flush()  # one at a time so the time-ordered ids keep the chat order
    db.commit()


def _write_fake_embeddings(db: Session, member_ids: list[str]) -> None:
    members = db.exec(select(EventMember).where(EventMember.id.in_(member_ids))).all()
    now = utcnow()
    rows = []
    for m in members:
        vector = fake_embedding(m.profile_text)
        m.embedding, m.embedded_at, m.snowflake_synced_at = vector, now if vector else None, None
        db.add(m)
        if vector is not None:
            rows.append(snowflake_store.EmbeddingRow(m.id, m.event_id, m.user_id, vector, now))
    db.commit()
    embeddings.sync_to_snowflake(rows)


def embed_seed_members(db: Session, member_ids: list[str], *, fake: bool) -> str:
    """Embed the seed members with Gemini when configured (and not `fake`), else fake vectors.
    Returns "gemini" or "fake"."""
    if not fake and not get_settings().gemini_configured:
        log.warning("GEMINI_API_KEY is not configured: writing deterministic fake embeddings "
                    "(hashed bag of words) instead")
        fake = True
    if not fake:
        started = utcnow()
        embeddings.embed_members(member_ids)  # also syncs to Snowflake when configured
        db.expire_all()
        missing = [
            m.id for m in db.exec(select(EventMember).where(EventMember.id.in_(member_ids))).all()
            if m.embedding is None or m.embedded_at is None or m.embedded_at < started
        ]
        if not missing:
            return "gemini"
        # Don't mix Gemini and fake vectors in one event: similarity between them is meaningless.
        log.warning("Gemini embedding failed for %d of %d seed member(s): falling back to fake "
                    "embeddings for all of them", len(missing), len(member_ids))
    _write_fake_embeddings(db, member_ids)
    return "fake"


def seed(db: Session, *, fake_embeddings: bool = False) -> SeedResult:
    """Create (or complete) the seed data and embed every seed member. Idempotent."""
    users = _upsert_people(db)
    org = _ensure_org(db, users)
    host = users[HOST_KEY]
    hacktx = _ensure_event(db, org, host, HACKTX)
    study = _ensure_event(db, org, host, STUDY)

    for p in PEOPLE:
        _join(db, hacktx, users[p.key], [p.role, p.idea, p.tracks],
              {"skills": p.skills, "experience_level": p.level}, p.socials)
        if p.study is not None:
            major, courses, style, availability = p.study
            _join(db, study, users[p.key], [courses, style, availability], {"major": major}, p.socials)
    # Rebuild every seed member's match text from the current profile (as the join does).
    for user in users.values():
        rebuild_member_texts(db, user.id)
    db.commit()

    groups = {name: _ensure_group(db, hacktx, users, name, keys) for name, keys in HACKTX_GROUPS}
    events = {"hacktx": hacktx, "study": study}
    for event_key, sender, target, outcome, message in REQUESTS:
        _ensure_request(db, events[event_key], users, groups, sender, target, outcome, message)
    _ensure_chat(db, groups["Team Pixel"], users)

    member_ids = list(
        db.exec(
            select(EventMember.id).where(
                EventMember.event_id.in_([hacktx.id, study.id]),
                EventMember.user_id.in_([u.id for u in users.values()]),
            )
        ).all()
    )
    embedded_with = embed_seed_members(db, member_ids, fake=fake_embeddings)
    return SeedResult(
        org_id=org.id,
        events={k: e.id for k, e in events.items()},
        users={k: u.id for k, u in users.items()},
        groups=groups,
        embedded_with=embedded_with,
        member_ids=member_ids,
    )


# --- CLI -----------------------------------------------------------------------------------------

def _check_migrated(engine) -> str | None:
    """Why the database isn't ready for seeding, or None."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()
    with engine.connect() as conn:
        if not inspect(conn).has_table("users"):
            return "the database has no schema"
        current = MigrationContext.configure(conn).get_current_revision()
    if current != head:
        return f"the database is at migration {current}, not {head}"
    return None


def print_summary(result: SeedResult) -> None:
    settings = get_settings()
    by_key = {p.key: p for p in [HOST, *PEOPLE]}
    print(f"\nSeeded org {ORG_NAME!r} ({result.org_id}), embeddings: {result.embedded_with}")
    print(f"  HackTX team-up (structured): {share_url(result.events['hacktx'])}")
    print(f"  Study buddies (informal):    {share_url(result.events['study'])}")
    print("\nLog in as a seed user with POST /api/auth/dev-login (use the exact name):")
    for key, note in LOGINS:
        print(f'  {{"email": "{seed_email(key)}", "name": "{by_key[key].name}"}}  - {note}')
    others = [f"{seed_email(p.key)} ({p.name})" for p in PEOPLE if p.key not in dict(LOGINS)]
    print(f"  Also: {', '.join(others)}")
    print(
        "\n  curl -c cookies.txt -H 'Content-Type: application/json' "
        f"-d '{{\"email\": \"{seed_email('priya')}\", \"name\": \"Priya Sharma\"}}' "
        "http://localhost:8001/api/auth/dev-login"
    )
    print(
        "  curl -b cookies.txt "
        f"http://localhost:8001/api/events/{result.events['hacktx']}/recommendations"
    )
    if not settings.is_dev_login_enabled():
        print("\n  Dev login is off: set DEV_LOGIN=1 and APP_ENV=local (localhost FRONTEND_ORIGIN).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed",
        description=f"Seed demo data (users @{SEED_DOMAIN}). Never touches other users.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true",
                      help="delete all seed data, then seed again (the demo reset)")
    mode.add_argument("--wipe", action="store_true", help="only delete all seed data")
    parser.add_argument("--fake-embeddings", action="store_true",
                        help="use deterministic local vectors instead of Gemini embeddings")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("app").setLevel(logging.INFO)

    engine = dbmod.get_engine()
    problem = _check_migrated(engine)
    if problem:
        print(f"Cannot seed: {problem}. Run `uv run alembic upgrade head` first.", file=sys.stderr)
        return 1
    with Session(engine) as db:
        if args.reset or args.wipe:
            counts = wipe(db)
            print(f"Removed seed data: {counts['users']} user(s), {counts['orgs']} org(s), "
                  f"{counts['events']} event(s)")
            if args.wipe:
                return 0
        result = seed(db, fake_embeddings=args.fake_embeddings)
    print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
