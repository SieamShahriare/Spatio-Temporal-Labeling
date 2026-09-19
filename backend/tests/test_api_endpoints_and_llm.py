"""
Comprehensive end-to-end test suite for database-facing API endpoints and LLM integration.
Runs against the live backend at http://localhost:8000.
"""

import asyncio
import time
import httpx
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
BASE_URL = "http://127.0.0.1:8000"  # not localhost — an unrelated process on this machine holds the IPv6 wildcard bind
DB_URL = os.getenv("DATABASE_URL")

async def run_all_tests():
    print(f"=== Starting E2E API & LLM Tests against {BASE_URL} ===\n")

    client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    try:
        # -------------------------------------------------------------
        # 1. Health check
        # -------------------------------------------------------------
        print("1. Testing GET /health...")
        res = await client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.status_code}"
        assert res.json() == {"ok": True}
        print("   ✓ Health check passed\n")

        # -------------------------------------------------------------
        # 2. Authentication Flow (Signup / Login / Auth Me)
        # -------------------------------------------------------------
        ts = int(time.time())
        test_email = f"test_annotator_{ts}@test.com"
        test_user = f"tester_{ts}"
        test_pass = "SecurePass123!"

        print(f"2. Testing Authentication (Signup with {test_email})...")
        signup_res = await client.post(
            "/auth/signup",
            json={"email": test_email, "username": test_user, "password": test_pass}
        )
        assert signup_res.status_code == 201, f"Signup failed: {signup_res.status_code} {signup_res.text}"
        signup_data = signup_res.json()
        csrf_token = signup_data["csrf_token"]
        assert csrf_token, "No CSRF token returned on signup"
        print(f"   ✓ User registered: ID {signup_data['user']['id']}, CSRF token obtained")

        # Set default headers for subsequent authenticated requests
        auth_headers = {
            "X-CSRF-Token": csrf_token,
        }

        me_res = await client.get("/auth/me", headers=auth_headers)
        assert me_res.status_code == 200, f"Auth me failed: {me_res.status_code}"
        me_data = me_res.json()
        assert me_data["user"]["email"] == test_email
        print(f"   ✓ GET /auth/me verified for user '{me_data['user']['username']}'\n")

        # -------------------------------------------------------------
        # 3. Direct Annotation Sessions API
        # -------------------------------------------------------------
        print("3. Testing Direct Annotation Sessions CRUD...")
        stem_text = "The doctor called at 8 AM. Two hours later, the patient arrived at the clinic."
        create_sess = await client.post("/sessions", json={"username": test_user, "stem_text": stem_text})
        assert create_sess.status_code == 201, f"Create session failed: {create_sess.text}"
        session_id = create_sess.json()["session_id"]
        print(f"   ✓ Created session ID {session_id}")

        get_sess = await client.get(f"/sessions/{session_id}")
        assert get_sess.status_code == 200
        assert get_sess.json()["stem_text"] == stem_text

        # Create two event spans
        span1_res = await client.post(
            f"/sessions/{session_id}/spans",
            json={
                "label_type": "Event",
                "span_text": "called",
                "char_start": 11,
                "char_end": 17,
                "tl_start": 10.0,
                "tl_end": 20.0,
                "source": "manual"
            }
        )
        assert span1_res.status_code == 201
        span1 = span1_res.json()
        assert span1["seq_label"] == "E1"

        span2_res = await client.post(
            f"/sessions/{session_id}/spans",
            json={
                "label_type": "Event",
                "span_text": "arrived",
                "char_start": 54,
                "char_end": 61,
                "tl_start": 40.0,
                "tl_end": 50.0,
                "source": "manual"
            }
        )
        assert span2_res.status_code == 201
        span2 = span2_res.json()
        assert span2["seq_label"] == "E2"
        print(f"   ✓ Added spans E1 (id={span1['id']}) and E2 (id={span2['id']})")

        # Update span position
        update_span = await client.patch(f"/spans/{span1['id']}", json={"tl_start": 12.0, "tl_end": 22.0})
        assert update_span.status_code == 200
        assert update_span.json()["tl_start"] == 12.0

        # Matrix build & save
        matrix_res = await client.get(f"/sessions/{session_id}/matrix")
        assert matrix_res.status_code == 200
        matrix_data = matrix_res.json()
        assert len(matrix_data["matrix"]) == 2
        print(f"   ✓ Computed relation matrix: {matrix_data['matrix']}")

        save_matrix = await client.post(f"/sessions/{session_id}/matrix/save")
        assert save_matrix.status_code == 200
        print("   ✓ Matrix saved to database")

        # Override cell (0, 1) and verify symmetric storage in relations table
        override_res = await client.patch(
            f"/sessions/{session_id}/matrix/override",
            json={"i": 0, "j": 1, "relation_code": 2}  # 2: meets
        )
        assert override_res.status_code == 200
        assert override_res.json()["matrix"][0][1] == 2
        assert override_res.json()["matrix"][1][0] == -2
        print("   ✓ Matrix cell overridden and inverse computed")

        # Verify symmetric rows in relations table directly via DB
        conn = await asyncpg.connect(DB_URL)
        r01 = await conn.fetchval(
            "SELECT relation_code FROM relations WHERE session_id=$1 AND span_i_id=$2 AND span_j_id=$3",
            session_id, span1["id"], span2["id"]
        )
        r10 = await conn.fetchval(
            "SELECT relation_code FROM relations WHERE session_id=$1 AND span_i_id=$2 AND span_j_id=$3",
            session_id, span2["id"], span1["id"]
        )
        assert r01 == 2 and r10 == -2, f"Relations asymmetry detected! r01={r01}, r10={r10}"
        print("   ✓ Verified symmetric relations in database (r01=2, r10=-2)")

        # Mark done & export
        await client.patch(f"/sessions/{session_id}/status", json={"status": "done"})
        exp_sess = await client.get(f"/sessions/{session_id}/export")
        assert exp_sess.status_code == 200
        assert len(exp_sess.json()["spans"]) == 2
        print("   ✓ Session exported successfully\n")

        # -------------------------------------------------------------
        # 4. Stems Pool & Batch Annotation Workflow
        # -------------------------------------------------------------
        print("4. Testing Stems Pool & Batches Workflow...")
        stems_res = await client.get("/stems?page=1&page_size=5")
        assert stems_res.status_code == 200
        stems_data = stems_res.json()
        print(f"   ✓ Stems listed: {stems_data['total']} total stems available")

        # Import a stem for testing
        test_stem_text = f"Early on Monday, Bob submitted the report. By noon, his supervisor approved it. ({ts})"
        import_res = await client.post(
            "/stems/import",
            headers=auth_headers,
            json={"texts": [test_stem_text]}
        )
        assert import_res.status_code == 200
        print("   ✓ Imported new stem")

        imported_stem_id = await conn.fetchval("SELECT id FROM stems WHERE text=$1", test_stem_text)
        assert imported_stem_id, "Imported stem not found in database"

        # Create a batch with this stem
        batch_res = await client.post(
            "/batches",
            headers=auth_headers,
            json={"name": f"Test Batch {ts}", "stem_ids": [imported_stem_id]}
        )
        assert batch_res.status_code == 201, f"Batch creation failed: {batch_res.text}"
        batch_id = batch_res.json()["id"]
        print(f"   ✓ Created batch ID {batch_id}")

        bs_row = await conn.fetchrow("SELECT id FROM batch_stems WHERE batch_id=$1 AND stem_id=$2", batch_id, imported_stem_id)
        batch_stem_id = bs_row["id"]

        # Get batch stem
        bs_res = await client.get(f"/batch-stems/{batch_stem_id}", headers=auth_headers)
        assert bs_res.status_code == 200
        assert bs_res.json()["stem_text"] == test_stem_text

        # Create batch span
        bspan1_res = await client.post(
            f"/batch-stems/{batch_stem_id}/spans",
            headers=auth_headers,
            json={
                "label_type": "Event",
                "span_text": "submitted the report",
                "char_start": 21,
                "char_end": 41,
                "tl_start": 10.0,
                "tl_end": 30.0,
                "source": "manual"
            }
        )
        assert bspan1_res.status_code == 201, f"Create batch span failed: {bspan1_res.text}"
        bspan1 = bspan1_res.json()
        assert bspan1["batch_stem_id"] == batch_stem_id
        # Verify in DB that batch span has proper batch_stem_id and session_id is NULL
        db_span = await conn.fetchrow("SELECT session_id, batch_stem_id FROM spans WHERE id=$1", bspan1["id"])
        assert db_span["session_id"] is None, "session_id must be NULL for batch spans"
        assert db_span["batch_stem_id"] == batch_stem_id, "batch_stem_id must match"
        print(f"   ✓ Created batch span ID {bspan1['id']} with normalized schema (session_id=NULL, batch_stem_id={batch_stem_id})")

        # Save batch matrix
        bsave_res = await client.post(f"/batch-stems/{batch_stem_id}/matrix/save", headers=auth_headers)
        assert bsave_res.status_code == 200
        print("   ✓ Saved batch matrix snapshot and relations")

        # Verify matrix_snapshots table has batch_stem_id and session_id is NULL
        db_snap = await conn.fetchrow("SELECT session_id, batch_stem_id FROM matrix_snapshots WHERE batch_stem_id=$1", batch_stem_id)
        assert db_snap["session_id"] is None
        assert db_snap["batch_stem_id"] == batch_stem_id
        print("   ✓ Verified matrix_snapshots has batch_stem_id and session_id=NULL")

        # Mark batch stem done
        done_res = await client.post(f"/batch-stems/{batch_stem_id}/mark-done", headers=auth_headers)
        assert done_res.status_code == 200
        print("   ✓ Batch stem marked done")

        # Export batch JSON
        b_export = await client.get(f"/batches/{batch_id}/export/json", headers=auth_headers)
        assert b_export.status_code == 200
        b_export_data = b_export.json()
        assert len(b_export_data["stems"]) == 1
        assert b_export_data["stems"][0]["batch_stem_id"] == batch_stem_id
        print("   ✓ Batch exported JSON verified with all stems included\n")

        # -------------------------------------------------------------
        # 5. LLM API Endpoints Testing
        # -------------------------------------------------------------
        print("5. Testing LLM Extraction Endpoints...")

        # Test unauthenticated access is properly rejected with 401 or 403
        unauth_events = await client.post("/api/extract-events", json={"text": "Alice woke up."})
        assert unauth_events.status_code in (401, 403), f"Expected 401 or 403 for unauthenticated extract-events, got {unauth_events.status_code}"
        print(f"   ✓ Unauthenticated /api/extract-events correctly rejected ({unauth_events.status_code})")

        narrative = "On Saturday morning at 7 AM, John woke up. Thirty minutes later, he made breakfast. At 9 AM, he left the house."
        print(f"   Calling /api/extract-events with narrative: '{narrative}'...")
        events_res = await client.post(
            "/api/extract-events",
            headers=auth_headers,
            json={"text": narrative}
        )
        assert events_res.status_code == 200, f"Extract events failed: {events_res.status_code} {events_res.text}"
        events_data = events_res.json()
        assert "events" in events_data and len(events_data["events"]) > 0
        print(f"   ✓ LLM extracted {len(events_data['events'])} events:")
        for ev in events_data["events"]:
            print(f"       - \"{ev['span_text']}\" [{ev['char_start']}:{ev['char_end']}]")

        # Test /api/llm-label-and-timeline on a fresh batch stem
        print("\n   Testing /api/llm-label-and-timeline...")
        llm_stem_text = "At dawn the rocket launched into orbit. Ten minutes later, the booster separated safely."
        llm_import = await client.post("/stems/import", headers=auth_headers, json={"texts": [llm_stem_text]})
        assert llm_import.status_code == 200
        llm_stem_id = await conn.fetchval("SELECT id FROM stems WHERE text=$1", llm_stem_text)
        
        llm_batch = await client.post("/batches", headers=auth_headers, json={"name": f"LLM Batch {ts}", "stem_ids": [llm_stem_id]})
        assert llm_batch.status_code == 201
        llm_batch_id = llm_batch.json()["id"]
        llm_bs_id = await conn.fetchval("SELECT id FROM batch_stems WHERE batch_id=$1 AND stem_id=$2", llm_batch_id, llm_stem_id)

        llm_full_res = await client.post(
            "/api/llm-label-and-timeline",
            headers=auth_headers,
            json={"batch_stem_id": llm_bs_id, "text": llm_stem_text}
        )
        assert llm_full_res.status_code == 200, f"llm_label_and_timeline failed: {llm_full_res.status_code} {llm_full_res.text}"
        llm_full_data = llm_full_res.json()
        assert len(llm_full_data["events"]) > 0
        print(f"   ✓ LLM labeled events and set timeline positions successfully:")
        for tu in llm_full_data["timeline_updated"]:
            print(f"       - {tu['seq_label']}: \"{tu['span_text']}\" timeline [{tu['tl_start']} - {tu['tl_end']}]")

        # Verify DB spans created by LLM have session_id=NULL and source='llm'
        llm_created_spans = await conn.fetch("SELECT id, session_id, batch_stem_id, source FROM spans WHERE batch_stem_id=$1", llm_bs_id)
        assert len(llm_created_spans) > 0
        for lcs in llm_created_spans:
            assert lcs["session_id"] is None
            assert lcs["batch_stem_id"] == llm_bs_id
            assert lcs["source"] == "llm"
        print("   ✓ Verified LLM spans in database adhere to normalized schema (session_id=NULL, source='llm')")

        print("\n=======================================================")
        print("🎉 ALL API & LLM TESTS COMPLETED AND PASSED WITH 100% SUCCESS!")
        print("=======================================================\n")

        await conn.close()

    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(run_all_tests())
