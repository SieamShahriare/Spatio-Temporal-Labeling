"""
Test Suite verifying that a reviewer can also act as an annotator:
1. Reviewer-1 builds their own batch.
2. Reviewer-1 labels spans -> stem status transitions from 'not_started' to 'in_progress'.
3. Reviewer-1 submits stem for review -> transitions to 'pending-review'.
4. Reviewer-1 is blocked from editing while stem is 'pending-review'.
5. Reviewer-1 cannot self-review/approve their own submission (HTTP 400).
6. Reviewer-2 can review and accept Reviewer-1's submission -> transitions to 'done'.
"""

import asyncio
import time
import os
import sys

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "../.env")))
from main import app
from database import get_pool, close_pool


async def run_tests():
    print("=== Running Reviewer as Annotator Integration Test Suite ===\n")
    transport = httpx.ASGITransport(app=app)
    ts = int(time.time() * 1000)

    rev1_email = f"rev1_{ts}@test.com"
    rev1_user = f"rev1_{ts}"
    rev2_email = f"rev2_{ts}@test.com"
    rev2_user = f"rev2_{ts}"
    password = "TestPassword123!"

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as r1_client, \
               httpx.AsyncClient(transport=transport, base_url="http://testserver") as r2_client:

        # 1. Sign up two reviewers
        res1 = await r1_client.post("/auth/signup", json={
            "email": rev1_email, "username": rev1_user, "password": password, "role": "reviewer"
        })
        assert res1.status_code == 201, f"Reviewer 1 signup failed: {res1.text}"
        r1_csrf = res1.json()["csrf_token"]
        r1_headers = {"X-CSRF-Token": r1_csrf}
        r1_id = res1.json()["user"]["id"]

        res2 = await r2_client.post("/auth/signup", json={
            "email": rev2_email, "username": rev2_user, "password": password, "role": "reviewer"
        })
        assert res2.status_code == 201, f"Reviewer 2 signup failed: {res2.text}"
        r2_csrf = res2.json()["csrf_token"]
        r2_headers = {"X-CSRF-Token": r2_csrf}
        r2_id = res2.json()["user"]["id"]
        print("1. Signed up two reviewers (Reviewer-1 and Reviewer-2).")

        # Insert a test stem
        pool = await get_pool()
        stem_text = f"Reviewer annotator test stem text {ts} with events and timeline."
        stem_id = await pool.fetchval(
            "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, 'test') RETURNING id",
            stem_text, len(stem_text.split())
        )

        # 2. Reviewer-1 builds their own batch
        create_batch_res = await r1_client.post("/batches", headers=r1_headers, json={
            "name": f"Batch_Rev1_{ts}",
            "stem_ids": [stem_id]
        })
        assert create_batch_res.status_code == 201, f"Batch creation failed: {create_batch_res.text}"
        batch_id = create_batch_res.json()["id"]

        get_batch_res = await r1_client.get(f"/batches/{batch_id}")
        assert get_batch_res.status_code == 200
        batch_data = get_batch_res.json()
        assert batch_data["owner_id"] == r1_id
        assert batch_data["owner_username"] == rev1_user
        assert len(batch_data["stems"]) == 1
        batch_stem_id = batch_data["stems"][0]["id"]
        assert batch_data["stems"][0]["status"] == "not_started"
        print(f"2. Reviewer-1 created batch #{batch_id} with stem #{batch_stem_id} (status: not_started).")

        # 3. Reviewer-1 annotates: adds span -> transitions to 'in_progress'
        span_res = await r1_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=r1_headers, json={
            "label_type": "Event",
            "span_text": "test stem text",
            "char_start": 19,
            "char_end": 33,
            "tl_start": 10.0,
            "tl_end": 20.0,
            "source": "manual"
        })
        assert span_res.status_code == 201, f"Span creation failed: {span_res.text}"

        check_bs = await r1_client.get(f"/batch-stems/{batch_stem_id}")
        assert check_bs.status_code == 200
        assert check_bs.json()["status"] == "in_progress", f"Expected 'in_progress', got {check_bs.json()['status']}"
        print("3. Reviewer-1 added a span -> stem automatically transitioned to 'in_progress'.")

        # 4. Reviewer-1 submits for review
        submit_res = await r1_client.post(f"/batch-stems/{batch_stem_id}/submit-for-review", headers=r1_headers)
        assert submit_res.status_code == 200, f"Submit failed: {submit_res.text}"
        assert submit_res.json()["status"] == "pending-review"

        check_bs_sub = await r1_client.get(f"/batch-stems/{batch_stem_id}")
        assert check_bs_sub.json()["status"] == "pending-review"
        print("4. Reviewer-1 submitted stem for review -> status is 'pending-review'.")

        # 5. Reviewer-1 cannot edit while in 'pending-review'
        edit_blocked_res = await r1_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=r1_headers, json={
            "label_type": "Time",
            "span_text": "events",
            "char_start": 44,
            "char_end": 50,
            "tl_start": 15.0,
            "tl_end": 25.0,
            "source": "manual"
        })
        assert edit_blocked_res.status_code == 400, "Reviewer-1 should be blocked from editing own pending-review stem"
        print("5. Reviewer-1 correctly blocked from editing own stem during 'pending-review'.")

        # 6. Reviewer-1 cannot self-review
        self_review_res = await r1_client.post(f"/batch-stems/{batch_stem_id}/review", headers=r1_headers, json={
            "decision": "accept"
        })
        assert self_review_res.status_code == 400, "Self-review should be rejected"
        assert "cannot review their own annotations" in self_review_res.text
        print("6. Reviewer-1 correctly blocked from self-reviewing their own annotations.")

        # 7. Reviewer-2 reviews and accepts Reviewer-1's submission
        queue_res = await r2_client.get("/reviews/pending")
        assert queue_res.status_code == 200
        pending_items = queue_res.json()
        found = [p for p in pending_items if p["batch_stem_id"] == batch_stem_id]
        assert len(found) == 1, "Reviewer-2 should see Reviewer-1's submission in review queue"
        assert found[0]["annotator_id"] == r1_id

        r2_review_res = await r2_client.post(f"/batch-stems/{batch_stem_id}/review", headers=r2_headers, json={
            "decision": "accept"
        })
        assert r2_review_res.status_code == 200, f"Reviewer-2 accept failed: {r2_review_res.text}"
        assert r2_review_res.json()["status"] == "done"

        final_bs = await r1_client.get(f"/batch-stems/{batch_stem_id}")
        assert final_bs.json()["status"] == "done"
        assert final_bs.json()["reviewer"]["id"] == r2_id
        assert final_bs.json()["completed_by"] == r1_id
        print(f"7. Reviewer-2 successfully evaluated and accepted Reviewer-1's submission (status: done).")

    print("\n✓ All 'Reviewer as Annotator' tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(run_tests())
