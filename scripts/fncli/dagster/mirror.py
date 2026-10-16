"""Client for the gitea-mirror service API (bearer token, JSON)."""

from fncli.dagster.utils import HttpClient


class MirrorAPI(HttpClient):
    def create_mirror(self, body: dict) -> dict:
        return self.post("/mirrors", json=body).json()

    def list_mirrors(self) -> list[dict]:
        return self.get("/mirrors").json()

    def get_status(self, mirror_id: int) -> dict:
        return self.get(f"/mirrors/{mirror_id}/status").json()

    def resync(self, mirror_id: int) -> dict:
        return self.post(f"/mirrors/{mirror_id}/resync").json()

    def sync_users(self, mirror_id: int) -> dict:
        return self.post(f"/mirrors/{mirror_id}/users/sync").json()

    def create_webhook(self, body: dict) -> dict:
        return self.post("/webhooks", json=body).json()

    def list_webhooks(self) -> list[dict]:
        return self.get("/webhooks").json()

    def list_deliveries(self, webhook_id: int, status: str | None) -> list[dict]:
        params = {"status": status} if status else {}
        return self.get(f"/webhooks/{webhook_id}/deliveries", params=params).json()
