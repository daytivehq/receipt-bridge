"""Fixed, non-inference CLI checks. Never return authentication files or raw CLI errors."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

PROVIDERS = ("codex", "claude", "agy")


def check_provider(provider: str, home: Path):
    if provider not in PROVIDERS:
        raise ValueError("지원하는 CLI 제공자를 선택하세요")
    result = {
        "provider": provider,
        "installed": bool(shutil.which(provider)),
        "auth": "unknown",
        "models": [],
    }
    if not result["installed"]:
        return {**result, "message": "CLI가 없습니다. 최신 분석 서비스 이미지로 업데이트하세요."}
    if provider == "claude":
        key = home / "anthropic-api-key"
        saved = key.is_file() and bool(key.read_text().strip())
        return {
            **result,
            "auth": "configured" if saved else "required",
            "message": "API 키가 저장되어 있습니다. 실제 인증은 분석 요청 시 확인됩니다."
            if saved
            else "아래에서 Claude API 키를 저장하세요. API 사용 요금이 발생할 수 있습니다.",
        }
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "LANG": "C.UTF-8",
    }
    if provider == "codex":
        env["CODEX_HOME"] = str(home / ".codex")
        command = ["codex", "login", "status"]
    else:
        command = ["agy", "models"]
    try:
        completed = subprocess.run(command, env=env, cwd="/tmp", capture_output=True, timeout=15, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return {**result, "message": "확인 시간이 초과됐습니다. 네트워크와 로그인 상태를 확인하세요."}
    if completed.returncode:
        return {
            **result,
            "auth": "required",
            "message": "로그인 또는 네트워크 확인이 필요합니다. 아래 로그인 안내를 확인하세요.",
        }
    if provider == "agy":
        text = completed.stdout[:100_000].decode(errors="replace")
        models = sorted(set(re.findall(r"\bgemini-[a-zA-Z0-9_.-]+", text)))[:100]
        return {
            **result,
            "auth": "unknown",
            "models": models,
            "message": "모델 목록을 불러왔습니다. Google 로그인·계정의 사용 권한은 별도 확인이 필요합니다.",
        }
    return {
        **result,
        "auth": "configured",
        "message": "로그인 정보가 있습니다. 만료·모델 사용 권한은 실제 분석 시 확인됩니다.",
    }
