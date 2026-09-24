import asyncio
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from database import get_pool, close_pool
from main import app

BASE_URL = "http://testserver"

async def test_completed_stems_readonly_flow():
    print("=== Testing Completed Stems Read-Only Mode & Access ===")
    transport = httpx.ASGITransport(app=app)
    ts = int(time.time() * 1000)

    annotator_email = f"ann_comp_{ts}@example.com"
    reviewer_email = f"rev_comp_{ts}@example.com"
    other_user_email = f"other_comp_{ts}@example.com"
    password = "password123"

    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as annotator_client, \
               httpx.AsyncClient(transport=transport, base_url=BASE_URL) as reviewer_client, \
               httpx.AsyncClient(transport=transport, base_url=BASE_URL) as other_client:
        # 1. Sign up annotator, reviewer, and another 3rd-party user
        reg_ann = await annotator_client.post("/auth/signup", json={"email": annotator_email, "username": f"ann_{ts}", "password": password})
        assert reg_ann.status_code == 201
        ann_headers = {"X-CSRF-Token": reg_ann.json()["csrf_token"]}

        reg_rev = await reviewer_client.post("/auth/signup", json={"email": reviewer_email, "username": f"rev_{ts}", "password": password, "role": "reviewer"})
        assert reg_rev.status_code == 201
        rev_headers = {"X-CSRF-Token": reg_rev.json()["csrf_token"]}

        reg_other = await other_client.post("/auth/signup", json={"email": other_user_email, "username": f"other_{ts}", "password": password})
        assert reg_other.status_code == 201
        other_headers = {"X-CSRF-Token": reg_other.json()["csrf_token"]}

        print("1. Signed up annotator, reviewer, and unrelated user accounts.")

        # 2. Create batch with stem
        pool = await get_pool()
        stem_text = f"The spaceship launched at noon. It reached orbit shortly after. Ground control cheered. {ts}"
        stem_row = await pool.fetchrow(
            "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, 'test') RETURNING id",
            stem_text, len(stem_text.split())
        )
        stem_id = stem_row["id"]

        batch_res = await annotator_client.post("/batches", headers=ann_headers, json={
            "name": f"Completed Batch {ts}", "stem_ids": [stem_id]
        })
        assert batch_res.status_code == 201, f"Batch creation failed: {batch_res.text}"
        batch_id = batch_res.json()["id"]

        bs_row = await pool.fetchrow("SELECT id FROM batch_stems WHERE batch_id = $1 AND stem_id = $2", batch_id, stem_id)
        batch_stem_id = bs_row["id"]

        # Annotator marks 2 spans and saves matrix
        s1 = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event", "span_text": "launched", "char_start": 14, "char_end": 22,
            "tl_start": 10.0, "tl_end": 25.0
        })
        assert s1.status_code == 201

        s2 = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event", "span_text": "reached orbit", "char_start": 35, "char_end": 48,
            "tl_start": 30.0, "tl_end": 50.0
        })
        assert s2.status_code == 201

        save_mat = await annotator_client.post(f"/batch-stems/{batch_stem_id}/matrix/save", headers=ann_headers)
        assert save_mat.status_code == 200

        # Submit for review
        sub_res = await annotator_client.post(f"/batch-stems/{batch_stem_id}/submit-for-review", headers=ann_headers)
        assert sub_res.status_code == 200, f"Submit for review failed: {sub_res.text}"
        print("2. Annotator created spans, saved matrix, and submitted stem for review.")

        # 3. Reviewer accepts and completes stem
        rev_dec = await reviewer_client.post(f"/batch-stems/{batch_stem_id}/review", headers=rev_headers, json={
            "decision": "accept",
            "comment": "Super clean temporal labeling. Approved!"
        })
        assert rev_dec.status_code == 200
        print("3. Reviewer approved stem (decision: 'accept'). Stem is now 'done'.")

        # 4. Verify GET /completed-stems returns the completed stem
        comp_res = await annotator_client.get("/completed-stems", headers=ann_headers)
        assert comp_res.status_code == 200
        comp_data = comp_res.json()
        assert comp_data["total"] >= 1
        found = next((item for item in comp_data["items"] if item["batch_stem_id"] == batch_stem_id), None)
        assert found is not None, "Completed stem not found in GET /completed-stems"
        assert found["status"] == "done"
        assert found["event_count"] == 2
        assert found["completed_by"]["username"] == f"ann_{ts}"
        assert found["reviewer"]["username"] == f"rev_{ts}"
        assert found["latest_review"]["comment"] == "Super clean temporal labeling. Approved!"
        print("4. Confirmed GET /completed-stems includes completed stem with full metadata.")

        # 5. Verify GET /stems populates completed_batch_stem_id and completed_batch_id
        stems_res = await annotator_client.get(f"/stems?search={stem_id}", headers=ann_headers)
        assert stems_res.status_code == 200
        stems_data = stems_res.json()
        stem_in_pool = next((s for s in stems_data["items"] if s["id"] == stem_id), None)
        assert stem_in_pool is not None
        assert stem_in_pool["state"] == "completed"
        assert stem_in_pool["completed_batch_stem_id"] == batch_stem_id
        assert stem_in_pool["completed_batch_id"] == batch_id
        print("5. Confirmed GET /stems provides completed_batch_stem_id for direct viewer links.")

        # 6. Read-Only Access by UNRELATED 3rd-party user:
        # A user who did NOT own the batch and is NOT a reviewer should now be able to read:
        # A. Batch Stem Detail
        other_detail = await other_client.get(f"/batch-stems/{batch_stem_id}", headers=other_headers)
        assert other_detail.status_code == 200, f"Expected 200 for read-only view, got {other_detail.status_code}: {other_detail.text}"
        assert other_detail.json()["status"] == "done"
        print("6. Confirmed unrelated user can view completed batch stem (200 OK).")

        # B. Spans
        other_spans = await other_client.get(f"/batch-stems/{batch_stem_id}/spans", headers=other_headers)
        assert other_spans.status_code == 200
        assert len(other_spans.json()) == 2
        print("   ✓ Unrelated user can read spans.")

        # C. Matrix
        other_mat = await other_client.get(f"/batch-stems/{batch_stem_id}/matrix", headers=other_headers)
        assert other_mat.status_code == 200
        assert len(other_mat.json()["span_order"]) == 2
        print("   ✓ Unrelated user can read relation matrix.")

        # D. Export JSON
        other_exp = await other_client.get(f"/batch-stems/{batch_stem_id}/export/json", headers=other_headers)
        assert other_exp.status_code == 200
        assert other_exp.json()["status"] == "done"
        print("   ✓ Unrelated user can download export JSON.")

        # E. Verify editing is STILL blocked for completed stems
        edit_attempt = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event", "span_text": "new event", "char_start": 0, "char_end": 5,
            "tl_start": 5.0, "tl_end": 10.0
        })
        assert edit_attempt.status_code == 400, "Editing a completed stem should be rejected with 400"
        print("7. Confirmed editing completed stem is strictly rejected (read-only enforced).")

    print("\nAll completed stems read-only tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_completed_stems_readonly_flow())
