import asyncio
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import server


class FakeModel:
    class TTSModel:
        sample_rate = 1000

    tts_model = TTSModel()

    def generate(self, **kwargs):
        return np.ones(max(1, len(kwargs["text"]) * 2), dtype=np.float32)


class LongFormTests(unittest.TestCase):
    def test_split_respects_limit_and_preserves_content(self):
        text = "第一句很短。第二句也很短！" + ("這是一個沒有標點的長句" * 30)
        chunks = server.split_long_text(text, max_chars=100)

        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(0 < len(chunk) <= 100 for chunk in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), text.replace(" ", ""))

    def test_long_job_combines_audio_and_pause(self):
        chunks = ["第一段。", "第二段。", "第三段。"]
        settings = {
            "mode": "design",
            "control": "溫暖女聲",
            "prompt_text": "",
            "cfg_value": 2.0,
            "inference_timesteps": 10,
            "normalize": False,
            "denoise": False,
            "seed": 42,
        }

        with tempfile.TemporaryDirectory() as directory:
            original_output = server.OUTPUT_DIR
            original_model = server.state.model
            try:
                server.OUTPUT_DIR = Path(directory)
                server.state.model = FakeModel()
                job_id = "a" * 32
                server.jobs[job_id] = server.GenerationJob(
                    id=job_id, total=len(chunks), created_at=1.0
                )
                asyncio.run(server._run_long_job(job_id, chunks, settings, None, 100))

                job = server.jobs[job_id]
                self.assertEqual(job.status, "completed")
                self.assertEqual(job.progress, 100)
                self.assertEqual(job.current, len(chunks))
                self.assertTrue((Path(directory) / job.filename).is_file())
            finally:
                server.OUTPUT_DIR = original_output
                server.state.model = original_model
                server.jobs.pop("a" * 32, None)

    def test_long_form_api_reports_progress_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            original_output = server.OUTPUT_DIR
            original_model = server.state.model
            try:
                server.OUTPUT_DIR = Path(directory)
                server.state.model = FakeModel()
                with TestClient(server.app) as client:
                    response = client.post(
                        "/api/generate",
                        data={
                            "text": "這是一個長文測試句子。" * 30,
                            "mode": "design",
                            "long_form": "true",
                            "segment_chars": "100",
                            "pause_ms": "50",
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    job_id = response.json()["job_id"]

                    for _ in range(20):
                        job = client.get(f"/api/jobs/{job_id}").json()
                        if job["status"] in {"completed", "failed"}:
                            break
                    self.assertEqual(job["status"], "completed")
                    self.assertEqual(job["progress"], 100)
                    self.assertTrue(job["audio_url"].startswith("/api/audio/"))
            finally:
                server.OUTPUT_DIR = original_output
                server.state.model = original_model

    def test_short_mode_rejects_text_over_2000_characters(self):
        with TestClient(server.app) as client:
            response = client.post(
                "/api/generate",
                data={"text": "字" * 2001, "mode": "design", "long_form": "false"},
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
