"""
E2E test for the group annotation workflow (Cohen's kappa / Krippendorff's alpha).
Runs against the live backend at http://localhost:8000 and a real database.
See context/cohen_kappa.md for the design.
"""
import asyncio
import time
import os
import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()
BASE_URL = "http://localhost:8000"
DB_URL = os.getenv("DATABASE_URL")


async def signup(client: httpx.AsyncClient, tag: str) -> dict:
    email = f"group_test_{tag}_{int(time.time() * 1000)}@test.com"
    res = await client.post("/auth/signup", json={
        "email": email, "password": "SecurePass123!", "username": f"tester_{tag}",
    })
    assert res.status_code == 201, f"Signup failed for {tag}: {res.status_code} {res.text}"
    data = res.json()
    return {"user": data["user"], "csrf": data["csrf_token"]}


async def run_all_tests():
    print("=== Group Annotation Workflow E2E Test ===\n")

    admin_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    event_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    t1_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    t2_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
    t3_client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    try:
        print("1. Signing up 4 users (creator, event annotator, 3 timeline annotators)...")
        admin = await signup(admin_client, "admin")
        event_annotator = await signup(event_client, "event")
        ta1 = await signup(t1_client, "t1")
        ta2 = await signup(t2_client, "t2")
        ta3 = await signup(t3_client, "t3")
        print(f"   ✓ Users created: admin={admin['user']['id']}, event={event_annotator['user']['id']}, "
              f"t1={ta1['user']['id']}, t2={ta2['user']['id']}, t3={ta3['user']['id']}\n")

        def hdr(session, extra=None):
            h = {"X-CSRF-Token": session["csrf"]}
            if extra:
                h.update(extra)
            return h

        print("2. GET /users lists all registered users...")
        res = await admin_client.get("/users")
        assert res.status_code == 200, res.text
        user_ids = {u["id"] for u in res.json()}
        assert admin["user"]["id"] in user_ids
        print(f"   ✓ {len(res.json())} users visible\n")

        print("3. Creating a fresh stem for this test run (group tasks are 1-per-stem)...")
        # Note: char_start/char_end on group-task event spans are metadata, not validated
        # against the stem's actual text (matches existing batch-span behavior).
        conn = await asyncpg.connect(DB_URL)
        try:
            stem_text = "Event A happened first. Then event B occurred. Finally event C took place."
            stem_row = await conn.fetchrow(
                "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, 'manual') RETURNING id",
                stem_text, len(stem_text.split())
            )
            stem_id = stem_row["id"]
        finally:
            await conn.close()
        print(f"   ✓ Stem {stem_id} created\n")

        res = await admin_client.post("/group-tasks", headers=hdr(admin), json={
            "stem_id": stem_id,
            "event_user_id": event_annotator["user"]["id"],
            "timeline_user_ids": [ta1["user"]["id"], ta2["user"]["id"], ta3["user"]["id"]],
        })
        assert res.status_code == 201, f"Create group task failed: {res.status_code} {res.text}"
        task = res.json()
        task_id = task["id"]
        assert task["status"] == "event_pending"
        assert len(task["members"]) == 4
        print(f"   ✓ Group task {task_id} created with 4 members\n")

        print("4. Duplicate task for same stem is rejected (409)...")
        res = await admin_client.post("/group-tasks", headers=hdr(admin), json={
            "stem_id": stem_id,
            "event_user_id": event_annotator["user"]["id"],
            "timeline_user_ids": [ta1["user"]["id"], ta2["user"]["id"], ta3["user"]["id"]],
        })
        assert res.status_code == 409, res.text
        print("   ✓ Duplicate correctly rejected\n")

        print("5. Non-event-annotator cannot add events (403)...")
        res = await t1_client.post(f"/group-tasks/{task_id}/events", headers=hdr(ta1), json={
            "span_text": "should fail", "char_start": 0, "char_end": 5,
        })
        assert res.status_code == 403, res.text
        print("   ✓ Correctly rejected\n")

        print("6. Event annotator adds 3 events and submits...")
        span_ids = []
        for text, start, end in [("Event A", 0, 7), ("event B", 26, 33), ("event C", 56, 63)]:
            res = await event_client.post(f"/group-tasks/{task_id}/events", headers=hdr(event_annotator), json={
                "span_text": text, "char_start": start, "char_end": end,
            })
            assert res.status_code == 201, res.text
            span_ids.append(res.json()["id"])
        print(f"   ✓ Created spans {span_ids}")

        res = await event_client.post(f"/group-tasks/{task_id}/submit-events", headers=hdr(event_annotator))
        assert res.status_code == 200, res.text
        task = res.json()
        assert task["status"] == "timelines_pending", task["status"]
        print("   ✓ Events submitted, task moved to timelines_pending\n")

        print("7. Event annotator can no longer add events after submit (409)...")
        res = await event_client.post(f"/group-tasks/{task_id}/events", headers=hdr(event_annotator), json={
            "span_text": "too late", "char_start": 0, "char_end": 5,
        })
        assert res.status_code == 409, res.text
        print("   ✓ Correctly rejected\n")

        print("8. Three timeline annotators submit near-identical positions independently...")
        base_positions = [(0.0, 10.0), (30.0, 40.0), (60.0, 70.0)]
        jitter = [0.0, 1.0, -1.0]
        for annotator_client, session, j in zip([t1_client, t2_client, t3_client], [ta1, ta2, ta3], jitter):
            positions = [
                {"span_id": sid, "tl_start": s + j, "tl_end": e + j}
                for sid, (s, e) in zip(span_ids, base_positions)
            ]
            res = await annotator_client.put(f"/group-tasks/{task_id}/my-timeline", headers=hdr(session), json={
                "positions": positions,
            })
            assert res.status_code == 200, res.text
            res = await annotator_client.post(f"/group-tasks/{task_id}/submit-timeline", headers=hdr(session))
            assert res.status_code == 200, f"submit-timeline failed: {res.status_code} {res.text}"
            task = res.json()
        print(f"   ✓ All 3 submitted. Final status: {task['status']}\n")

        print("9. Agreement scores are computed and high (near-identical positions)...")
        assert task["status"] in ("accepted", "accepted_flagged"), task["status"]
        assert task["krippendorff_alpha"] is not None
        assert task["krippendorff_alpha"] > 0.9, task["krippendorff_alpha"]
        assert task["cohens_kappa_avg"] == 1.0, task["cohens_kappa_avg"]
        assert task["fleiss_kappa"] == 1.0, task["fleiss_kappa"]
        print(f"   ✓ alpha={task['krippendorff_alpha']:.4f}, "
              f"cohen_avg={task['cohens_kappa_avg']}, fleiss={task['fleiss_kappa']}\n")

        print("10. A timeline annotator cannot re-submit after done (409)...")
        res = await t1_client.put(f"/group-tasks/{task_id}/my-timeline", headers=hdr(ta1), json={
            "positions": [{"span_id": span_ids[0], "tl_start": 99, "tl_end": 100}],
        })
        assert res.status_code == 409, res.text
        print("   ✓ Correctly rejected (immutability after submission)\n")

        print("11. GET /group-tasks/{id}/agreement returns full breakdown...")
        res = await admin_client.get(f"/group-tasks/{task_id}/agreement", headers=hdr(admin))
        assert res.status_code == 200, res.text
        agreement = res.json()
        assert agreement["agreement_details"] is not None
        assert len(agreement["agreement_details"]["per_event"]) == 3
        print("   ✓ Agreement breakdown present for all 3 events\n")

        print("12. Task creator can manually override the decision...")
        res = await admin_client.post(f"/group-tasks/{task_id}/accept", headers=hdr(admin), json={
            "decision": "accepted",
        })
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "accepted"
        print("   ✓ Decision override applied\n")

        print("13. Non-creator cannot override the decision (403)...")
        res = await t1_client.post(f"/group-tasks/{task_id}/accept", headers=hdr(ta1), json={
            "decision": "rejected",
        })
        assert res.status_code == 403, res.text
        print("   ✓ Correctly rejected\n")

        print("14. GET /group-tasks/dashboard returns aggregated stats...")
        res = await admin_client.get("/group-tasks/dashboard", headers=hdr(admin))
        assert res.status_code == 200, res.text
        dash = res.json()
        assert dash["completed_with_scores"] >= 1
        print(f"   ✓ Dashboard: {dash}\n")

        print("=== ALL GROUP ANNOTATION TESTS PASSED ===")

    finally:
        for c in (admin_client, event_client, t1_client, t2_client, t3_client):
            await c.aclose()


if __name__ == "__main__":
    asyncio.run(run_all_tests())
