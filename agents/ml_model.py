import numpy as np
from sklearn.neighbors import NearestNeighbors

# In-memory mock database of groups and candidates for SquadUp
GROUPS_DB = [
    {
        "group_id": "grp-101",
        "group_name": "HackTX AI Builders",
        "event_id": "evt-structured-1",
        "interests": ["ai", "machine learning", "python", "agents"],
        "target_skill_level": 3,
        "target_group_size": 4,
        "weekly_hours": 20.0,
        "members": ["user-1", "user-2"]
    }
]

def recommend_candidates_mock(viewer_id: str, candidates: list[dict]) -> list[dict]:
    """
    Reranks candidates and generates fallback reasons if the agent is offline.
    """
    ranked = []
    for c in candidates:
        if c.get("user_id") == viewer_id:
            continue
        ranked.append({
            "user_id": c.get("user_id"),
            "name": c.get("name", "Candidate"),
            "reason": f"Strong alignment in {c.get('skills', ['tech'])[0]} with matching availability.",
            "compatibility_score": 88.5
        })
    return ranked[:10]