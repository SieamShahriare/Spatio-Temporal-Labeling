import asyncio
import time
import httpx
from database import get_pool, close_pool
from main import app

BASE_URL = "http://testserver"

async def test_span_renumber_flow():
    print("=== Testing Span Renumbering / Shift on Delete ===")
    ts = int(time.time() * 1000)
    user_email = f"user_renumber_{ts}@example.com"
    user_pass = "password123"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        # 1. Sign up
        reg_res = await client.post("/auth/signup", json={
            "email": user_email,
            "username": f"user_renumber_{ts}",
            "password": user_pass
        })
        assert reg_res.status_code == 201, f"Signup failed: {reg_res.text}"
        csrf_token = reg_res.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf_token}

        # 2. Create batch with 1 stem
        pool = await get_pool()
        stem_text = f"First event happened. Second event followed. Third event emerged. Fourth event concluded. {ts}"
        stem_row = await pool.fetchrow(
            "INSERT INTO stems (text, word_count, source) VALUES ($1, $2, 'test') RETURNING id",
            stem_text, len(stem_text.split())
        )
        stem_id = stem_row["id"]

        batch_res = await client.post("/batches", headers=headers, json={
            "name": f"Renumber Batch {ts}",
            "stem_ids": [stem_id]
        })
        assert batch_res.status_code == 201
        batch_id = batch_res.json()["id"]

        bs_row = await pool.fetchrow("SELECT id FROM batch_stems WHERE batch_id = $1 AND stem_id = $2", batch_id, stem_id)
        assert bs_row is not None
        batch_stem_id = bs_row["id"]

        # 3. Create 4 Event spans: E1, E2, E3, E4
        spans_created = []
        for i in range(1, 5):
            res = await client.post(f"/batch-stems/{batch_stem_id}/spans", headers=headers, json={
                "label_type": "Event",
                "span_text": f"Event {i}",
                "char_start": (i - 1) * 20,
                "char_end": i * 20,
                "tl_start": float(i * 10),
                "tl_end": float(i * 10 + 5)
            })
            assert res.status_code == 201, f"Failed to create span {i}: {res.text}"
            data = res.json()
            assert data["seq_label"] == f"E{i}", f"Expected E{i}, got {data['seq_label']}"
            spans_created.append(data)

        print("1. Successfully created 4 Event spans: E1, E2, E3, E4.")

        # 4. Also create 2 Time spans: T1, T2
        time_spans = []
        for i in range(1, 3):
            res = await client.post(f"/batch-stems/{batch_stem_id}/spans", headers=headers, json={
                "label_type": "Time",
                "span_text": f"Time {i}",
                "char_start": 100 + (i - 1) * 10,
                "char_end": 100 + i * 10,
                "tl_start": float(i * 5),
                "tl_end": float(i * 5 + 2)
            })
            assert res.status_code == 201
            assert res.json()["seq_label"] == f"T{i}"
            time_spans.append(res.json())
        print("2. Successfully created 2 Time spans: T1, T2.")

        # 5. Delete E3 (index 2 of spans_created)
        e3_id = spans_created[2]["id"]
        del_res = await client.delete(f"/batch-stems/{batch_stem_id}/spans/{e3_id}", headers=headers)
        assert del_res.status_code == 204, f"Delete failed: {del_res.text}"
        print("3. Deleted span E3.")

        # 6. Fetch spans and verify E4 shifted to E3
        list_res = await client.get(f"/batch-stems/{batch_stem_id}/spans")
        assert list_res.status_code == 200
        spans_after = list_res.json()
        event_spans_after = [s for s in spans_after if s["label_type"] == "Event"]
        assert len(event_spans_after) == 3, f"Expected 3 event spans, got {len(event_spans_after)}"

        labels = [s["seq_label"] for s in event_spans_after]
        assert labels == ["E1", "E2", "E3"], f"Expected ['E1', 'E2', 'E3'], got {labels}"
        # Former E4 (id spans_created[3]['id']) should now have seq_label E3
        e4_turned_e3 = next(s for s in event_spans_after if s["id"] == spans_created[3]["id"])
        assert e4_turned_e3["seq_label"] == "E3"
        print("   ✓ Verified remaining event spans shifted cleanly to ['E1', 'E2', 'E3'].")

        # 7. Check database rows directly
        db_rows = await pool.fetch(
            "SELECT id, seq_label FROM spans WHERE batch_stem_id = $1 AND label_type = 'Event' ORDER BY created_at, id",
            batch_stem_id
        )
        db_labels = [r["seq_label"] for r in db_rows]
        assert db_labels == ["E1", "E2", "E3"], f"DB labels mismatch: expected ['E1', 'E2', 'E3'], got {db_labels}"
        print("   ✓ Verified database records have updated seq_labels in PostgreSQL.")

        # 8. Add a new event span: it should become E4 (not duplicate E3 or E4)
        new_event = await client.post(f"/batch-stems/{batch_stem_id}/spans", headers=headers, json={
            "label_type": "Event",
            "span_text": "Event 5 newly marked",
            "char_start": 80,
            "char_end": 95,
            "tl_start": 50.0,
            "tl_end": 55.0
        })
        assert new_event.status_code == 201
        assert new_event.json()["seq_label"] == "E4", f"Expected new span to be E4, got {new_event.json()['seq_label']}"
        print("4. Added next marked event: verified it is cleanly named E4.")

        # 9. Delete E1 (the first span)
        e1_id = spans_created[0]["id"]
        del_e1 = await client.delete(f"/batch-stems/{batch_stem_id}/spans/{e1_id}", headers=headers)
        assert del_e1.status_code == 204

        list_res2 = await client.get(f"/batch-stems/{batch_stem_id}/spans")
        assert list_res2.status_code == 200
        event_spans_after2 = [s for s in list_res2.json() if s["label_type"] == "Event"]
        labels2 = [s["seq_label"] for s in event_spans_after2]
        assert labels2 == ["E1", "E2", "E3"], f"Expected ['E1', 'E2', 'E3'] after deleting E1, got {labels2}"
        print("5. Deleted E1: verified remaining spans shifted down to ['E1', 'E2', 'E3'].")

        # 10. Check matrix calculation aligns with new span order
        mat_res = await client.get(f"/batch-stems/{batch_stem_id}/matrix")
        assert mat_res.status_code == 200
        mat_data = mat_res.json()
        mat_span_labels = [s["seq_label"] for s in mat_data["span_order"]]
        assert mat_span_labels == ["E1", "E2", "E3"], f"Matrix span order mismatch: {mat_span_labels}"
        print("6. Verified relation matrix automatically uses updated sequential span order.")

        # 11. Test Time span deletion: delete T1, check T2 becomes T1
        t1_id = time_spans[0]["id"]
        del_t1 = await client.delete(f"/batch-stems/{batch_stem_id}/spans/{t1_id}", headers=headers)
        assert del_t1.status_code == 204

        list_res3 = await client.get(f"/batch-stems/{batch_stem_id}/spans")
        time_spans_after = [s for s in list_res3.json() if s["label_type"] == "Time"]
        assert len(time_spans_after) == 1
        assert time_spans_after[0]["seq_label"] == "T1", f"Expected T1, got {time_spans_after[0]['seq_label']}"
        print("7. Deleted T1: verified former T2 shifted to T1.")

    print("\nAll span renumbering tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_span_renumber_flow())
