from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx


class RemoteError(Exception):
    def __init__(self, service: str, status: int = 0, retry_after: float = 0):
        # Never retain response bodies, auth headers, tokens or URLs in an error.
        self.status = status
        self.retry_after = retry_after
        self.retryable = status in {0, 408, 429} or status >= 500
        super().__init__(f"{service} 요청 실패 (HTTP {status or '연결 오류'})")


def retry_delay(response: httpx.Response) -> float:
    try:
        return min(3600, max(0, float(response.headers.get("Retry-After", "0"))))
    except ValueError:
        return 60


class Ledger:
    def __init__(self, base_url: str, password: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=40,
            headers={"Authorization": "Bearer " + password, "Accept-Language": "ko"},
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        self.http.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise RemoteError("가계부") from None
        if not response.is_success:
            raise RemoteError("가계부", response.status_code, retry_delay(response))
        try:
            return response.json()
        except ValueError:
            raise RemoteError("가계부 응답 형식") from None

    def context(self, account_id):
        accounts = self.request("GET", "accounts")
        account = next((a for a in accounts if a["id"] == account_id), None)
        if not account:
            raise ValueError("설정한 계좌가 없거나 앱 비밀번호에 허용되지 않았습니다")
        categories = self.request("GET", "categories", params={"account": account_id, "kind": "expense"})
        return account, categories

    def create(self, payload: dict, key: str) -> str:
        result = self.request("POST", "transactions", json=payload, headers={"Idempotency-Key": key})
        if not isinstance(result.get("id"), str) or not result["id"]:
            raise RemoteError("가계부 거래 ID")
        return result["id"]

    def attach(self, posting_id: str, image: Path) -> str:
        with image.open("rb") as f:
            result = self.request(
                "POST",
                f"transactions/{quote(posting_id, safe='')}/receipts",
                files={"file": ("receipt.jpg", f, "image/jpeg")},
            )
        if not isinstance(result.get("id"), str) or not result["id"]:
            raise RemoteError("가계부 영수증 ID")
        return result["id"]
