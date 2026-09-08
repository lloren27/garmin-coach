from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from garminconnect import Garmin

from .sync import TOKENSTORE, get_activities, parse_date, sport


ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

WATTWISE_API_URL = os.getenv("WATTWISE_API_URL", "http://127.0.0.1:8010").rstrip("/")
WATTWISE_ACCESS_TOKEN = os.getenv("WATTWISE_ACCESS_TOKEN", "")
STATE_FILE = Path(os.getenv("WATTWISE_BRIDGE_STATE_FILE", ROOT / "data" / "wattwise_bridge_state.json")).expanduser()
LOOKBACK_DAYS = int(os.getenv("WATTWISE_BRIDGE_DAYS", "60"))
LIMIT = int(os.getenv("WATTWISE_BRIDGE_LIMIT", "12"))
SPORTS = {
    item.strip().lower()
    for item in os.getenv("WATTWISE_BRIDGE_SPORTS", "running,cycling").split(",")
    if item.strip()
}
RUNNING_FORMAT = os.getenv("WATTWISE_BRIDGE_RUNNING_FORMAT", "tcx").lower()
CYCLING_FORMAT = os.getenv("WATTWISE_BRIDGE_CYCLING_FORMAT", "original").lower()


def auth_headers() -> dict[str, str]:
    if not WATTWISE_ACCESS_TOKEN:
        raise RuntimeError("Falta WATTWISE_ACCESS_TOKEN. Ejecuta ./install_wattwise_core.command primero.")
    return {"Authorization": f"Bearer {WATTWISE_ACCESS_TOKEN}"}


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"imported_activity_ids": [], "failed_activity_ids": []}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check_wattwise() -> None:
    response = httpx.get(f"{WATTWISE_API_URL}/readyz", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") not in {"ready", "ok"}:
        raise RuntimeError(f"wattwise-core no esta listo: {payload}")


def candidate_activities(client: Garmin, state: dict[str, Any]) -> list[dict[str, Any]]:
    imported = set(str(item) for item in state.get("imported_activity_ids", []))
    failed = set(str(item) for item in state.get("failed_activity_ids", []))
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    candidates = []
    for activity in get_activities(client):
        activity_id = str(activity.get("activityId") or "")
        if not activity_id or activity_id in imported or activity_id in failed:
            continue
        activity_date = parse_date(activity.get("startTimeLocal") or activity.get("startTimeGMT"))
        if not activity_date or activity_date < cutoff:
            continue
        activity_sport = sport(activity)
        if activity_sport not in SPORTS:
            continue
        candidates.append(
            {
                "id": activity_id,
                "date": activity_date.isoformat(),
                "name": activity.get("activityName") or activity_sport,
                "sport": activity_sport,
            }
        )
    return sorted(candidates, key=lambda item: item["date"])[-LIMIT:]


def download_activity_file(client: Garmin, activity: dict[str, Any], output_dir: Path) -> Path:
    file_format = preferred_format(activity)
    download_format = {
        "original": Garmin.ActivityDownloadFormat.ORIGINAL,
        "fit": Garmin.ActivityDownloadFormat.ORIGINAL,
        "tcx": Garmin.ActivityDownloadFormat.TCX,
        "gpx": Garmin.ActivityDownloadFormat.GPX,
    }.get(file_format)
    if download_format is None:
        raise RuntimeError(f"Formato wattwise no soportado para {activity['sport']}: {file_format}")

    raw = client.download_activity(str(activity["id"]), dl_fmt=download_format)
    if file_format in {"tcx", "gpx"}:
        path = output_dir / f"{activity['id']}.{file_format}"
        path.write_bytes(raw)
        return path

    zip_path = output_dir / f"{activity['id']}.zip"
    zip_path.write_bytes(raw)
    if zipfile.is_zipfile(zip_path):
        with zipfile.ZipFile(zip_path) as archive:
            fit_names = [name for name in archive.namelist() if name.lower().endswith((".fit", ".fit.gz"))]
            if not fit_names:
                raise RuntimeError("El original de Garmin no contiene FIT")
            name = fit_names[0]
            suffix = ".fit.gz" if name.lower().endswith(".fit.gz") else ".fit"
            fit_path = output_dir / f"{activity['id']}{suffix}"
            fit_path.write_bytes(archive.read(name))
            return fit_path
    fit_path = output_dir / f"{activity['id']}.fit"
    fit_path.write_bytes(raw)
    return fit_path


def preferred_format(activity: dict[str, Any]) -> str:
    if activity.get("sport") == "running":
        return RUNNING_FORMAT
    if activity.get("sport") == "cycling":
        return CYCLING_FORMAT
    return "original"


def upload_to_wattwise(path: Path) -> dict[str, Any]:
    content_type = "application/xml" if path.suffix.lower() in {".tcx", ".gpx"} else "application/octet-stream"
    with path.open("rb") as file:
        response = httpx.post(
            f"{WATTWISE_API_URL}/v1/imports",
            headers=auth_headers(),
            files={"file": (path.name, file, content_type)},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()


def wattwise_activity(import_job_id: str | None) -> dict[str, Any]:
    if not import_job_id:
        raise RuntimeError("Wattwise no devolvio import_job_id")
    response = httpx.get(f"{WATTWISE_API_URL}/v1/activities/{import_job_id}", headers=auth_headers(), timeout=30)
    if response.status_code == 404:
        raise RuntimeError("Wattwise acepto el archivo, pero no creo actividad canonica")
    response.raise_for_status()
    return response.json()


def bridge_activity(client: Garmin, activity: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="garmin-wattwise-") as tmp:
        activity_path = download_activity_file(client, activity, Path(tmp))
        result = upload_to_wattwise(activity_path)
    import_job_id = result.get("import_job_id") or result.get("id")
    canonical = wattwise_activity(import_job_id)
    return {
        "activity_id": activity["id"],
        "date": activity["date"],
        "sport": activity["sport"],
        "name": activity["name"],
        "format": activity_path.suffix.lstrip("."),
        "import_job_id": import_job_id,
        "wattwise_activity_id": canonical.get("activity_id"),
        "has_power": canonical.get("has_power"),
        "has_hr": canonical.get("has_hr"),
        "has_gps": canonical.get("has_gps"),
        "status": result.get("status"),
    }


def main() -> int:
    check_wattwise()
    state = load_state()
    client = Garmin()
    client.login(str(TOKENSTORE))
    candidates = candidate_activities(client, state)

    imported = []
    failed = []
    for activity in candidates:
        try:
            result = bridge_activity(client, activity)
            imported.append(result)
            state.setdefault("imported_activity_ids", []).append(activity["id"])
        except Exception as exc:
            failed.append({"activity_id": activity["id"], "name": activity["name"], "error": str(exc)[:300]})
            state.setdefault("failed_activity_ids", []).append(activity["id"])

    state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_imported"] = imported
    state["last_failed"] = failed
    save_state(state)
    print(json.dumps({"ok": not failed, "imported": imported, "failed": failed}, indent=2, ensure_ascii=False))
    return 1 if failed and not imported else 0


if __name__ == "__main__":
    raise SystemExit(main())
