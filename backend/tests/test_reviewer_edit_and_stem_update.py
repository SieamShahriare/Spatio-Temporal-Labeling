"""
Test Suite for:
1. Reviewer permissions to edit spans (create, update timeline, delete) on pending-review stems.
2. Reviewer permissions to save and override Allen matrices.
3. Stem text update endpoint (PATCH /batch-stems/{batch_stem_id}/stem) for annotators and reviewers.
4. Automatic cascading reset of spans, relations, and matrix snapshots when stem text changes.
5. Authorization checks preventing unauthorized annotators from editing other users' batch stems.
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
    print("=== Running Reviewer Editing & Stem Text Update Test Suite ===\n")
    transport = httpx.ASGITransport(app=app)
    ts = int(time.time() * 1000)

    # 1. Sign up annotator and reviewer
    annotator_email = f"annotator_{ts}@test.com"
    annotator_user = f"annotator_{ts}"
    reviewer_email = f"reviewer_{ts}@test.com"
    reviewer_user = f"reviewer_{ts}"
    unauth_email = f"unauth_{ts}@test.com"
    unauth_user = f"unauth_{ts}"
    password = "TestPassword123!"

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as annotator_client, \
               httpx.AsyncClient(transport=transport, base_url="http://testserver") as reviewer_client, \
               httpx.AsyncClient(transport=transport, base_url="http://testserver") as unauth_client:

        # Signup Annotator
        res = await annotator_client.post("/auth/signup", json={
            "email": annotator_email, "username": annotator_user, "password": password, "role": "annotator"
        })
        assert res.status_code == 201, f"Annotator signup failed: {res.text}"
        ann_csrf = res.json()["csrf_token"]
        ann_headers = {"X-CSRF-Token": ann_csrf}

        # Signup Reviewer
        res = await reviewer_client.post("/auth/signup", json={
            "email": reviewer_email, "username": reviewer_user, "password": password, "role": "reviewer"
        })
        assert res.status_code == 201, f"Reviewer signup failed: {res.text}"
        rev_csrf = res.json()["csrf_token"]
        rev_headers = {"X-CSRF-Token": rev_csrf}

        # Signup Unauth Annotator
        res = await unauth_client.post("/auth/signup", json={
            "email": unauth_email, "username": unauth_user, "password": password, "role": "annotator"
        })
        assert res.status_code == 201, f"Unauth signup failed: {res.text}"
        unauth_csrf = res.json()["csrf_token"]
        unauth_headers = {"X-CSRF-Token": unauth_csrf}

        print("1. Signed up annotator, reviewer, and unauthorized annotator accounts.")

        # 2. Import stem and create batch as annotator
        initial_stem = f"Alice woke up at 7 AM. She drank coffee and read the newspaper before going to work. {ts}"
        import_res = await annotator_client.post("/stems/import", headers=ann_headers, json={"texts": [initial_stem]})
        assert import_res.status_code == 200, f"Stem import failed: {import_res.text}"

        pool = await get_pool()
        stem_row = await pool.fetchrow("SELECT id FROM stems WHERE text = $1", initial_stem)
        assert stem_row is not None, "Imported stem not found in DB"
        stem_id = stem_row["id"]

        batch_res = await annotator_client.post("/batches", headers=ann_headers, json={
            "name": f"Test Batch {ts}", "stem_ids": [stem_id]
        })
        assert batch_res.status_code == 201, f"Batch creation failed: {batch_res.text}"
        batch_id = batch_res.json()["id"]

        bs_row = await pool.fetchrow("SELECT id FROM batch_stems WHERE batch_id = $1 AND stem_id = $2", batch_id, stem_id)
        assert bs_row is not None, "Batch stem row not found"
        batch_stem_id = bs_row["id"]
        print(f"2. Created batch #{batch_id} with batch_stem #{batch_stem_id}")

        # 3. Annotator adds spans and submits for review
        # Span 1: "woke up"
        s1 = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event",
            "span_text": "woke up",
            "char_start": 6,
            "char_end": 13,
            "tl_start": 10.0,
            "tl_end": 20.0
        })
        assert s1.status_code == 201, f"Create span 1 failed: {s1.text}"
        span1_id = s1.json()["id"]

        # Span 2: "drank coffee"
        s2 = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event",
            "span_text": "drank coffee",
            "char_start": 29,
            "char_end": 41,
            "tl_start": 25.0,
            "tl_end": 35.0
        })
        assert s2.status_code == 201, f"Create span 2 failed: {s2.text}"
        span2_id = s2.json()["id"]

        # Save matrix as annotator
        mat_res = await annotator_client.post(f"/batch-stems/{batch_stem_id}/matrix/save", headers=ann_headers)
        assert mat_res.status_code == 200, f"Matrix save failed: {mat_res.text}"

        # Submit for review
        sub_res = await annotator_client.post(f"/batch-stems/{batch_stem_id}/submit-for-review", headers=ann_headers)
        assert sub_res.status_code == 200, f"Submit for review failed: {sub_res.text}"
        print("3. Annotator labeled 2 spans, saved matrix, and submitted stem for review (status: pending-review).")

        # Verify annotator CANNOT edit spans while in pending-review
        ann_blocked = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event", "span_text": "read the newspaper", "char_start": 46, "char_end": 64
        })
        assert ann_blocked.status_code == 400, "Annotator should be blocked from adding spans in pending-review"
        print("   ✓ Annotator correctly blocked from editing during pending-review.")

        # 4. Reviewer editing operations while in pending-review
        # A. Reviewer adds Span 3: "read the newspaper"
        rev_span = await reviewer_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=rev_headers, json={
            "label_type": "Event",
            "span_text": "read the newspaper",
            "char_start": 46,
            "char_end": 64,
            "tl_start": 40.0,
            "tl_end": 55.0
        })
        assert rev_span.status_code == 201, f"Reviewer failed to add span: {rev_span.text}"
        span3_id = rev_span.json()["id"]
        print("4. Reviewer added new span while in review mode.")

        # Check status remains pending-review
        bs_check = await reviewer_client.get(f"/batch-stems/{batch_stem_id}")
        assert bs_check.status_code == 200
        assert bs_check.json()["status"] == "pending-review", "Status should remain pending-review after reviewer edit"
        print("   ✓ Stem status preserved as 'pending-review' after reviewer edit.")

        # B. Reviewer updates timeline on Span 1
        update_span = await reviewer_client.patch(
            f"/batch-stems/{batch_stem_id}/spans/{span1_id}",
            headers=rev_headers,
            json={"tl_start": 12.0, "tl_end": 22.0}
        )
        assert update_span.status_code == 200, f"Reviewer failed to update span: {update_span.text}"
        assert update_span.json()["tl_start"] == 12.0
        print("   ✓ Reviewer updated span timeline positions.")

        # C. Reviewer saves and recomputes matrix
        rev_mat_save = await reviewer_client.post(f"/batch-stems/{batch_stem_id}/matrix/save", headers=rev_headers)
        assert rev_mat_save.status_code == 200, f"Reviewer failed to save matrix: {rev_mat_save.text}"
        print("   ✓ Reviewer saved & recomputed relation matrix.")

        # D. Reviewer overrides a matrix relation
        rev_mat_override = await reviewer_client.patch(
            f"/batch-stems/{batch_stem_id}/matrix/override",
            headers=rev_headers,
            json={"i": 0, "j": 1, "relation_code": 1}
        )
        assert rev_mat_override.status_code == 200, f"Reviewer failed to override matrix: {rev_mat_override.text}"
        print("   ✓ Reviewer overrode matrix cell.")

        # E. Reviewer deletes a span
        rev_delete = await reviewer_client.delete(
            f"/batch-stems/{batch_stem_id}/spans/{span3_id}",
            headers=rev_headers
        )
        assert rev_delete.status_code == 204, f"Reviewer failed to delete span: {rev_delete.text}"
        print("   ✓ Reviewer deleted span.")

        # 5. Stem text update by Reviewer (modifying stem text in review mode)
        new_text = f"Alice woke up at 6 AM. She drank hot coffee before leaving for the office. {ts}"
        update_stem_res = await reviewer_client.patch(
            f"/batch-stems/{batch_stem_id}/stem",
            headers=rev_headers,
            json={"stem_text": new_text}
        )
        assert update_stem_res.status_code == 200, f"Reviewer failed to update stem text: {update_stem_res.text}"
        res_data = update_stem_res.json()
        assert res_data["stem_text"] == new_text
        assert res_data["word_count"] == len(new_text.split())
        print("5. Reviewer updated stem text via PATCH /batch-stems/{id}/stem.")

        # Verify DB updated and old annotations were cascaded/reset
        db_stem = await pool.fetchrow("SELECT * FROM stems WHERE id = $1", stem_id)
        assert db_stem["text"] == new_text
        assert db_stem["word_count"] == len(new_text.split())

        remaining_spans = await pool.fetch("SELECT * FROM spans WHERE batch_stem_id = $1", batch_stem_id)
        assert len(remaining_spans) == 0, f"Expected spans to be cleared, found {len(remaining_spans)}"

        remaining_rel = await pool.fetch("SELECT * FROM relations WHERE batch_stem_id = $1", batch_stem_id)
        assert len(remaining_rel) == 0, f"Expected relations to be cleared, found {len(remaining_rel)}"

        remaining_snapshots = await pool.fetch("SELECT * FROM matrix_snapshots WHERE batch_stem_id = $1", batch_stem_id)
        assert len(remaining_snapshots) == 0, f"Expected matrix_snapshots to be cleared, found {len(remaining_snapshots)}"
        print("   ✓ Confirmed stems table updated, and all spans/relations/matrix snapshots were reset.")

        # 6. Reviewer requests re-evaluation so annotator can edit stem text and re-annotate
        review_decision = await reviewer_client.post(
            f"/batch-stems/{batch_stem_id}/review",
            headers=rev_headers,
            json={"decision": "re-evaluate", "comment": "Stem updated and spans cleared, please re-annotate."}
        )
        assert review_decision.status_code == 200, f"Review decision failed: {review_decision.text}"
        print("6. Reviewer set decision to re-evaluate.")

        # 7. Annotator edits stem text while in re-evaluate
        annotator_updated_text = f"Alice woke up at 6:30 AM. She grabbed fresh coffee and left. {ts}"
        ann_stem_update = await annotator_client.patch(
            f"/batch-stems/{batch_stem_id}/stem",
            headers=ann_headers,
            json={"stem_text": annotator_updated_text}
        )
        assert ann_stem_update.status_code == 200, f"Annotator stem update failed: {ann_stem_update.text}"
        assert ann_stem_update.json()["stem_text"] == annotator_updated_text
        print("7. Annotator successfully updated stem text while in re-evaluate.")

        # 8. Unauthorized user cannot edit stem text or spans
        unauth_update = await unauth_client.patch(
            f"/batch-stems/{batch_stem_id}/stem",
            headers=unauth_headers,
            json={"stem_text": "Hacked stem text"}
        )
        assert unauth_update.status_code == 404, f"Expected 404 for unauth user, got {unauth_update.status_code}"

        unauth_span = await unauth_client.post(
            f"/batch-stems/{batch_stem_id}/spans",
            headers=unauth_headers,
            json={"label_type": "Event", "span_text": "grabbed", "char_start": 28, "char_end": 35}
        )
        assert unauth_span.status_code == 404, f"Expected 404 for unauth span creation, got {unauth_span.status_code}"
        print("8. Unauthorized user correctly blocked with 404.")

        # 9. Release to Pool after stem was marked as Done
        # First, add a span and submit & accept it
        s_done = await annotator_client.post(f"/batch-stems/{batch_stem_id}/spans", headers=ann_headers, json={
            "label_type": "Event", "span_text": "grabbed fresh coffee", "char_start": 28, "char_end": 48
        })
        assert s_done.status_code == 201
        await annotator_client.post(f"/batch-stems/{batch_stem_id}/matrix/save", headers=ann_headers)
        await annotator_client.post(f"/batch-stems/{batch_stem_id}/submit-for-review", headers=ann_headers)

        accept_res = await reviewer_client.post(f"/batch-stems/{batch_stem_id}/review", headers=rev_headers, json={"decision": "accept"})
        assert accept_res.status_code == 200

        # Check stem state in stems pool: should be completed
        stems_res = await annotator_client.get(f"/stems?search={stem_id}")
        assert stems_res.status_code == 200
        stem_item = next(it for it in stems_res.json()["items"] if it["id"] == stem_id)
        assert stem_item["state"] == "completed", f"Expected state 'completed', got {stem_item['state']}"
        print("9. Stem marked as 'done' and verified state 'completed' in stem pool.")

        # Now Reviewer releases the completed stem to pool
        release_res = await reviewer_client.post(
            f"/batch-stems/{batch_stem_id}/review",
            headers=rev_headers,
            json={"decision": "release_to_pool", "comment": "Releasing done stem back to pool"}
        )
        assert release_res.status_code == 200

        # Verify annotations were deleted
        spans_after = await pool.fetch("SELECT * FROM spans WHERE batch_stem_id = $1", batch_stem_id)
        assert len(spans_after) == 0, f"Expected 0 spans, got {len(spans_after)}"

        # Verify stem state returned to 'available'
        stems_res2 = await annotator_client.get(f"/stems?search={stem_id}")
        assert stems_res2.status_code == 200
        stem_item2 = next(it for it in stems_res2.json()["items"] if it["id"] == stem_id)
        assert stem_item2["state"] == "available", f"Expected state 'available', got {stem_item2['state']}"
        print("   ✓ Released 'done' stem to pool: all annotations deleted and state is 'available' again.")

        print("\nAll integration tests passed successfully!")


if __name__ == "__main__":
    asyncio.run(run_tests())
