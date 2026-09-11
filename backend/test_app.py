"""Run: python -m unittest discover -s backend -p test_app.py
Requires the app dependencies and httpx. Uses only an in-memory database.
"""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool


class AppRegressionTest(unittest.TestCase):
    def test_validation_progress_transactions_and_cascades(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        spec = importlib.util.spec_from_file_location("isolated_app", Path(__file__).with_name("app.py"))
        module = importlib.util.module_from_spec(spec)
        with patch("sqlalchemy.create_engine", return_value=engine):
            spec.loader.exec_module(module)
        self.addCleanup(engine.dispose)
        commits, statements = [], []
        event.listen(engine, "commit", lambda connection: commits.append(True))
        event.listen(engine, "before_cursor_execute", lambda connection, cursor, statement, parameters, context, many: statements.append(statement))
        with TestClient(module.app) as client:
            payload = {"title": " Plan ", "owner": " Jack ", "target_date": "2026-09-11"}
            def post(url, data):
                response = client.post(url, json=data)
                self.assertEqual(response.status_code, 201, response.text)
                return response.json()

            self.assertEqual(client.get("/api/dashboard/stats").json()["overall_progress"], 0)
            for changes in ({"title": "  "}, {"owner": ""}, {"target_date": "2026-02-30"}, {"target_date": "20260911"}, {"status": "invalid"}, {"status": None}):
                self.assertEqual(client.post("/api/priorities", json=payload | changes).status_code, 422)
            priority = post("/api/priorities", payload)
            self.assertEqual(priority["title"], "Plan")
            action_url = f"/api/priorities/{priority['id']}/actions"
            self.assertEqual(client.post(action_url, json=payload | {"owner": " "}).status_code, 422)
            action = post(action_url, payload)
            detail_url = f"/api/actions/{action['id']}"
            self.assertEqual(client.post(detail_url + "/subactions", json={"title": " ", "due_date": "2026-09-11"}).status_code, 422)
            sub_payload = {"title": "Step", "due_date": "2026-09-11"}
            commits.clear()
            sub = post(detail_url + "/subactions", sub_payload)
            self.assertEqual(len(commits), 1)
            toggle_url = f"/api/subactions/{sub['id']}/toggle"
            commits.clear()
            self.assertEqual(client.patch(toggle_url).json()["action_progress"], 100)
            self.assertEqual(len(commits), 1)
            second = post(detail_url + "/subactions", sub_payload)
            self.assertEqual(client.get(detail_url).json()["progress"], 50)

            # Cached values may be stale in an existing database; GETs must agree without writing.
            with module.SessionLocal() as db:
                db.get(module.Action, action["id"]).progress = 7
                db.commit()
            commits.clear()
            self.assertEqual(client.get("/api/actions").json()[0]["progress"], 50)
            self.assertEqual(client.get(detail_url).json()["progress"], 50)
            self.assertEqual(client.get(action_url).json()[0]["progress"], 50)
            self.assertEqual(client.get("/api/priorities").json()[0]["progress"], 50)
            self.assertEqual(client.get(f"/api/priorities/{priority['id']}").json()["actions"][0]["progress"], 50)
            self.assertEqual(client.get("/api/dashboard/stats").json()["overall_progress"], 50)
            self.assertEqual(commits, [])

            # A failed commit must roll back the step and its progress together.
            with patch.object(module.SessionLocal.class_, "commit", side_effect=RuntimeError("commit failed")):
                with self.assertRaisesRegex(RuntimeError, "commit failed"):
                    client.patch(toggle_url)
            self.assertTrue(client.get(detail_url).json()["subactions"][0]["completed"])
            commits.clear()
            self.assertEqual(client.delete(f"/api/subactions/{second['id']}").status_code, 200)
            self.assertEqual(len(commits), 1)
            self.assertEqual(client.get(detail_url).json()["progress"], 100)
            self.assertEqual(client.get("/api/dashboard/stats").json()["completed_count"], 1)

            review = {"reviewer_name": "Jack", "date": "2026-09-11", "comment": "Checked", "status": "Approved"}
            for changes in ({"comment": " "}, {"date": "bad"}, {"status": "invalid"}):
                self.assertEqual(client.post(detail_url + "/reviews", json=review | changes).status_code, 422)
            post(detail_url + "/reviews", review)
            for _ in range(8):
                other = post("/api/priorities", payload)
                post(f"/api/priorities/{other['id']}/actions", payload)
            statements.clear()
            client.get("/api/priorities")
            self.assertEqual(len(statements), 3)
            statements.clear()
            client.get("/api/actions")
            self.assertEqual(len(statements), 2)
            self.assertEqual(client.delete(f"/api/priorities/{priority['id']}").status_code, 200)
            self.assertEqual(client.get(detail_url).status_code, 404)
            self.assertEqual(client.patch(toggle_url).status_code, 404)
            with module.SessionLocal() as db:
                self.assertEqual(db.query(module.Review).count(), 0)
                self.assertEqual(db.query(module.SubAction).count(), 0)


if __name__ == "__main__":
    unittest.main()
