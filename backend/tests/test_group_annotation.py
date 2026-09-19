"""
E2E test for the redesigned group annotation workflow: distribution,
always-editable submissions with recompute, per-member matrix override,
event-set-change invalidation, reassignment, and the D7 membership-based
score-visibility gate. Runs against the live backend at http://localhost:8000
and a real database. See context/group_workflow_redesign.md for the design.
"""
import asyncio
import time
import os
import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()
BASE_URL = "http://127.0.0.1:8000"  # not localhost — an unrelated process on this machine holds the IPv6 wildcard bind
DB_URL = os.getenv("DATABASE_URL")


async def signup(client: httpx.AsyncClient, tag: str) -> dict:
    email = f"redesign_{tag}_{int(time.time() * 1000)}@test.com"
    res = await client.post("/auth/signup", json={
        "email": email, "password": "SecurePass123!", "username": f"redesign_{tag}",
    })
    assert res.status_code == 201, f"Signup failed for {tag}: {res.status_code} {res.text}"
    data = res.json()
    return {"user": data["user"], "csrf": data["csrf_token"]}


def hdr(session):
    return {"X-CSRF-Token": session["csrf"]}


async def run_all_tests():
    print("=== Redesigned Group Workflow E2E Test ===\n")

    admin_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    pool_clients = [httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) for _ in range(5)]

    try:
        print("1. Signing up admin (distributor, stays a non-participant) + 5-person pool...")
        admin = await signup(admin_client, "admin")
        pool_sessions = [await signup(c, f"p{i}") for i, c in enumerate(pool_clients)]
        pool_ids = [s["user"]["id"] for s in pool_sessions]
        clients_by_id = {s["user"]["id"]: c for s, c in zip(pool_sessions, pool_clients)}
        sessions_by_id = {s["user"]["id"]: s for s in pool_sessions}
        print(f"   ✓ admin={admin['user']['id']}, pool={pool_ids}\n")

        print("2. Creating a fresh stem and distributing it to the first 4 of the pool...")
        conn = await asyncpg.connect(DB_URL)
        try:
            stem_row = await conn.fetchrow(
                "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, 'manual') RETURNING id",
                "Event A happened first. Then event B occurred. Finally event C took place.", 12
            )
            stem_id = stem_row["id"]
        finally:
            await conn.close()

        distribute_pool = pool_ids[:4]
        res = await admin_client.post("/group-tasks/distribute", headers=hdr(admin), json={
            "stem_ids": [stem_id], "pool_user_ids": distribute_pool,
        })
        assert res.status_code == 201, f"Distribute failed: {res.status_code} {res.text}"
        dist = res.json()
        assert dist["pool_size"] == 4
        assert len(dist["created_task_ids"]) == 1
        assert dist["skipped"] == []
        task_id = dist["created_task_ids"][0]
        print(f"   ✓ Task {task_id} created via distribution run {dist['distribution_run_id']}\n")

        print("3. Pool size below 4 is rejected...")
        res = await admin_client.post("/group-tasks/distribute", headers=hdr(admin), json={
            "stem_ids": [stem_id], "pool_user_ids": pool_ids[:3],
        })
        assert res.status_code == 400, res.text
        print("   ✓ Correctly rejected\n")

        print("4. Reading task detail as admin (non-participant) to discover role assignment...")
        res = await admin_client.get(f"/group-tasks/{task_id}", headers=hdr(admin))
        assert res.status_code == 200, res.text
        task = res.json()
        assert task["scores_hidden"] is False
        members = task["members"]
        assert len(members) == 4
        event_member = next(m for m in members if m["role"] == "event_annotator")
        timeline_members = [m for m in members if m["role"] == "timeline_annotator"]
        assert len(timeline_members) == 3
        event_uid = event_member["user_id"]
        timeline_uids = [m["user_id"] for m in timeline_members]
        print(f"   ✓ event_annotator={event_uid}, timeline_annotators={timeline_uids}\n")

        print("5. GET /my-tasks shows the assignment; timeline annotators are blocked...")
        res = await clients_by_id[timeline_uids[0]].get("/my-tasks", headers=hdr(sessions_by_id[timeline_uids[0]]))
        assert res.status_code == 200, res.text
        my_tasks = res.json()
        this_task = next(t for t in my_tasks if t["task_id"] == task_id)
        assert this_task["blocked"] is True
        assert this_task["role"] == "timeline_annotator"
        print("   ✓ Correctly blocked pending events\n")

        print("6. Non-participant cannot view agreement scores before they exist either (403)...")
        res = await admin_client.get(f"/group-tasks/{task_id}/agreement", headers=hdr(admin))
        assert res.status_code == 200, res.text  # admin is non-participant, allowed even if scores are null
        res = await clients_by_id[event_uid].get(f"/group-tasks/{task_id}/agreement", headers=hdr(sessions_by_id[event_uid]))
        assert res.status_code == 403, res.text
        print("   ✓ Admin allowed, participant rejected\n")

        print("7. Event annotator adds 3 events and submits...")
        event_session = sessions_by_id[event_uid]
        event_client = clients_by_id[event_uid]
        span_ids = []
        for text, start, end in [("Event A", 0, 7), ("event B", 26, 33), ("event C", 56, 63)]:
            res = await event_client.post(f"/group-tasks/{task_id}/events", headers=hdr(event_session), json={
                "span_text": text, "char_start": start, "char_end": end,
            })
            assert res.status_code == 201, res.text
            span_ids.append(res.json()["id"])
        res = await event_client.post(f"/group-tasks/{task_id}/submit-events", headers=hdr(event_session))
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "timelines_pending"
        print(f"   ✓ Spans {span_ids} created and events submitted\n")

        print("8. Three timeline annotators submit near-identical positions independently...")
        base_positions = [(0.0, 10.0), (30.0, 40.0), (60.0, 70.0)]
        jitter = [0.0, 1.0, -1.0]
        for uid, j in zip(timeline_uids, jitter):
            c, s = clients_by_id[uid], sessions_by_id[uid]
            positions = [{"span_id": sid, "tl_start": st + j, "tl_end": en + j} for sid, (st, en) in zip(span_ids, base_positions)]
            res = await c.put(f"/group-tasks/{task_id}/my-timeline", headers=hdr(s), json={"positions": positions})
            assert res.status_code == 200, res.text
            res = await c.post(f"/group-tasks/{task_id}/submit-timeline", headers=hdr(s))
            assert res.status_code == 200, f"submit-timeline failed: {res.status_code} {res.text}"
        task = res.json()
        assert task["status"] == "computed", task["status"]
        assert task["scores_hidden"] is True  # the submitting client is a participant
        print(f"   ✓ All 3 submitted; task status={task['status']}\n")

        print("9. Admin (non-participant) sees computed scores; participants still see none...")
        res = await admin_client.get(f"/group-tasks/{task_id}", headers=hdr(admin))
        admin_view = res.json()
        assert admin_view["krippendorff_alpha"] is not None
        assert admin_view["krippendorff_alpha"] > 0.9, admin_view["krippendorff_alpha"]
        assert admin_view["cohens_kappa_avg"] == 1.0
        assert admin_view["outcome"] in ("accepted", "accepted_flagged")

        res = await event_client.get(f"/group-tasks/{task_id}", headers=hdr(event_session))
        participant_view = res.json()
        assert participant_view["scores_hidden"] is True
        assert participant_view["krippendorff_alpha"] is None
        assert participant_view["outcome"] is None
        print(f"   ✓ admin alpha={admin_view['krippendorff_alpha']:.4f}; participant view fully hidden\n")

        print("10. D1: a timeline annotator edits their position AFTER full completion...")
        edit_uid = timeline_uids[0]
        c, s = clients_by_id[edit_uid], sessions_by_id[edit_uid]
        res = await c.put(f"/group-tasks/{task_id}/my-timeline", headers=hdr(s), json={
            "positions": [{"span_id": span_ids[0], "tl_start": 50.0, "tl_end": 55.0}],
        })
        assert res.status_code == 200, f"Edit-after-submit should be allowed (D1): {res.status_code} {res.text}"
        res = await admin_client.get(f"/group-tasks/{task_id}", headers=hdr(admin))
        task = res.json()
        assert task["status"] == "timelines_pending", task["status"]
        assert task["scores_stale"] is True
        print("   ✓ Edit accepted, task reopened, scores marked stale\n")

        print("11. Matrix override: the edited annotator overrides a cell before re-submitting...")
        res = await c.patch(f"/group-tasks/{task_id}/my-matrix/override", headers=hdr(s), json={
            "i": 0, "j": 1, "relation_code": 5,  # force 'during' regardless of derived positions
        })
        assert res.status_code == 200, res.text
        matrix_after_override = res.json()["matrix"]
        assert matrix_after_override[0][1] == 5
        assert matrix_after_override[1][0] == -5
        print("   ✓ Override applied and inverse mirrored\n")

        print("12. Re-submitting preserves the override, and recompute fires once all 3 resubmit...")
        res = await c.post(f"/group-tasks/{task_id}/submit-timeline", headers=hdr(s))
        assert res.status_code == 200, res.text
        # The other two are still 'submitted' from before -> recompute should fire immediately.
        res = await admin_client.get(f"/group-tasks/{task_id}", headers=hdr(admin))
        task = res.json()
        assert task["status"] == "computed", task["status"]
        assert task["scores_stale"] is False
        assert task["cohens_kappa_avg"] < 1.0, "override should have broken perfect kappa agreement"
        print(f"   ✓ Recomputed: cohens_kappa_avg={task['cohens_kappa_avg']:.4f} (< 1.0, override registered)\n")

        print("13. Revision and agreement-run history are visible to non-participants only...")
        res = await admin_client.get(f"/group-tasks/{task_id}/revisions", headers=hdr(admin))
        assert res.status_code == 200, res.text
        revisions = res.json()
        assert any(r["user_id"] == edit_uid and r["revision_no"] == 2 for r in revisions)
        res = await admin_client.get(f"/group-tasks/{task_id}/agreement-runs", headers=hdr(admin))
        assert res.status_code == 200, res.text
        runs = res.json()
        assert len(runs) == 2, f"expected 2 agreement runs, got {len(runs)}"
        res = await event_client.get(f"/group-tasks/{task_id}/revisions", headers=hdr(event_session))
        assert res.status_code == 403, res.text
        print(f"   ✓ {len(revisions)} revisions, {len(runs)} agreement runs; participant blocked\n")

        print("14. Event annotator adds a 4th event span AFTER timelines were submitted (§5.5 cascade)...")
        res = await event_client.post(f"/group-tasks/{task_id}/events", headers=hdr(event_session), json={
            "span_text": "a fourth event", "char_start": 70, "char_end": 84,
        })
        assert res.status_code == 201, res.text
        new_span_id = res.json()["id"]
        res = await admin_client.get(f"/group-tasks/{task_id}", headers=hdr(admin))
        task = res.json()
        assert task["status"] == "timelines_pending", task["status"]
        assert task["scores_stale"] is True
        for m in task["members"]:
            if m["role"] == "timeline_annotator":
                assert m["status"] == "in_progress", f"{m['user_id']} should be reopened: {m['status']}"
        print("   ✓ All 3 timeline submissions superseded by the new event\n")

        print("15. Reassignment: hand off an un-submitted timeline slot to a 5th pool member...")
        fifth_uid = pool_ids[4]
        target_member = next(m for m in task["members"] if m["role"] == "timeline_annotator")
        res = await admin_client.post(
            f"/group-tasks/{task_id}/members/{target_member['id']}/reassign",
            headers=hdr(admin), json={"user_id": fifth_uid},
        )
        assert res.status_code == 200, res.text
        reassigned_task = res.json()
        reassigned = next(m for m in reassigned_task["members"] if m["id"] == target_member["id"])
        assert reassigned["user_id"] == fifth_uid
        assert reassigned["status"] == "pending"
        print(f"   ✓ Reassigned from {target_member['user_id']} to {fifth_uid}\n")

        print("16. Reassigning to someone who already holds a role on the stem is rejected...")
        other_member = next(m for m in task["members"] if m["role"] == "event_annotator")
        res = await admin_client.post(
            f"/group-tasks/{task_id}/members/{target_member['id']}/reassign",
            headers=hdr(admin), json={"user_id": other_member["user_id"]},
        )
        assert res.status_code == 400, res.text
        print("   ✓ Correctly rejected\n")

        print("17. Manual decision: non-participant sets it, participant is blocked...")
        res = await event_client.post(f"/group-tasks/{task_id}/accept", headers=hdr(event_session), json={"decision": "rejected"})
        assert res.status_code == 403, res.text
        res = await admin_client.post(f"/group-tasks/{task_id}/accept", headers=hdr(admin), json={"decision": "adjudication"})
        assert res.status_code == 200, res.text
        assert res.json()["decision"] == "adjudication"
        res = await admin_client.post(f"/group-tasks/{task_id}/accept", headers=hdr(admin), json={"decision": None})
        assert res.status_code == 200, res.text
        assert res.json()["decision"] is None
        print("   ✓ Decision set, blocked for participants, and reopened\n")

        print("=== ALL REDESIGNED WORKFLOW TESTS PASSED ===")

    finally:
        await admin_client.aclose()
        for c in pool_clients:
            await c.aclose()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
