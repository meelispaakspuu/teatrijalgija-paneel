"""GitHubi REST API: data-haru failide lugemine/kirjutamine ja workflow käivitamine."""
from __future__ import annotations

import base64
import json

import httpx

API = "https://api.github.com"


class GitHubStore:
    def __init__(self, token: str, repo: str, branch: str = "data", workflow: str = "watch.yml"):
        self.repo, self.branch, self.workflow = repo, branch, workflow
        self.client = httpx.Client(
            base_url=API, timeout=20,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )

    def read(self, path: str, branch: str | None = None) -> tuple[str | None, str | None]:
        """Tagastab (sisu, sha). Puuduva faili korral (None, None)."""
        ref = branch or self.branch
        r = self.client.get(f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        meta = r.json()
        if meta.get("content"):
            return base64.b64decode(meta["content"]).decode("utf-8"), meta["sha"]
        # > 1 MB failid: sisu tuleb eraldi raw-päringuga
        raw = self.client.get(f"/repos/{self.repo}/contents/{path}", params={"ref": ref},
                              headers={"Accept": "application/vnd.github.raw+json"})
        raw.raise_for_status()
        return raw.text, meta["sha"]

    def read_json(self, path: str) -> dict:
        text, _ = self.read(path)
        return json.loads(text) if text else {}

    def write(self, path: str, text: str, sha: str | None, message: str, branch: str | None = None) -> str:
        body = {"message": message, "branch": branch or self.branch,
                "content": base64.b64encode(text.encode("utf-8")).decode()}
        if sha:
            body["sha"] = sha
        r = self.client.put(f"/repos/{self.repo}/contents/{path}", json=body)
        if r.status_code == 409:
            raise RuntimeError("Faili muudeti vahepeal mujal. Värskenda lehte ja proovi uuesti.")
        if r.status_code in (403, 404) and path.startswith(".github/workflows/"):
            raise PermissionError("Tokenil puudub õigus workflow-faili muuta. Lisa fine-grained tokenile "
                                  "õigus „Workflows: Read and write“ (GitHub → Settings → Developer settings "
                                  "→ Fine-grained tokens → teatrijalgija-paneel → Edit).")
        r.raise_for_status()
        return r.json()["content"]["sha"]

    def dispatch(self, manual: bool = True, test_notify: bool = False) -> None:
        r = self.client.post(
            f"/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches",
            json={"ref": "main", "inputs": {"manual": str(manual).lower(),
                                            "test_notify": str(test_notify).lower()}},
        )
        r.raise_for_status()

    def runs(self, n: int = 8) -> list[dict]:
        r = self.client.get(f"/repos/{self.repo}/actions/workflows/{self.workflow}/runs",
                            params={"per_page": n})
        r.raise_for_status()
        return r.json().get("workflow_runs", [])
