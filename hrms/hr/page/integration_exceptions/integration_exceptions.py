from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import frappe
from frappe import _

try:
	import requests
except ImportError:
	requests = None

PAGE = "integration-exceptions"
DEFAULT_BASE_URL = "http://127.0.0.1:18081"
REPORT_FIELDS = (
	"id",
	"runId",
	"kind",
	"severity",
	"dingtalkKey",
	"hrmsDocname",
	"detail",
	"createdAt",
	"status",
	"statusReason",
)
VALID_STATUSES = {"ACTIVE", "REVIEW", "STALE", "RESOLVED"}


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
	try:
		number = int(value)
	except (TypeError, ValueError, OverflowError):
		number = default
	return max(minimum, min(maximum, number))


def _check_access() -> None:
	user = frappe.session.user
	if not user or user == "Guest" or frappe.get_cached_value("User", user, "user_type") != "System User":
		frappe.throw(_("当前账号无权查看集成异常报告"), frappe.PermissionError)

	if not frappe.get_cached_doc("Page", PAGE).is_permitted():
		frappe.throw(_("当前账号无权查看集成异常报告"), frappe.PermissionError)


def _empty_summary() -> dict:
	return {"total": 0, "byKind": {}, "bySeverity": {}, "byStatus": {}}


def _clean_report(value) -> dict | None:
	if not isinstance(value, dict):
		return None
	return {field: value.get(field) for field in REPORT_FIELDS}


def _count_reports(reports: list[dict], field: str) -> dict:
	counts = {}
	for report in reports:
		key = report.get(field) or "UNKNOWN"
		counts[str(key)] = counts.get(str(key), 0) + 1
	return counts


def _count_statuses(reports: list[dict]) -> dict:
	counts = {}
	for report in reports:
		status = str(report.get("status") or "").strip().upper()
		if status not in VALID_STATUSES:
			status = "REVIEW"
		counts[status] = counts.get(status, 0) + 1
	return counts


def _summary(reports: list[dict]) -> dict:
	return {
		"total": len(reports),
		"byKind": _count_reports(reports, "kind"),
		"bySeverity": _count_reports(reports, "severity"),
		"byStatus": _count_statuses(reports),
	}


def _fetch_json(url: str):
	headers = {"Accept": "application/json"}
	if requests is not None:
		response = requests.get(url, headers=headers, timeout=8)
		response.raise_for_status()
		return response.json()

	request = Request(url, headers=headers, method="GET")
	with urlopen(request, timeout=8) as response:
		return json.load(response)


def _service_error(error: Exception) -> str:
	status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
	if isinstance(status_code, int):
		return _("组织同步服务返回 HTTP {0}，请稍后重试。").format(status_code)
	if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
		return _("组织同步服务在 8 秒内未响应，请稍后重试。")
	return _("组织同步服务暂时不可用，请稍后重试。")


@frappe.whitelist(methods=["GET"])
def get_reports(hours: int = 168, limit: int = 2000) -> dict:
	"""Proxy read-only reconciliation reports after checking Desk page access."""
	_check_access()

	hours = _bounded_int(hours, 168, 1, 8760)
	limit = _bounded_int(limit, 2000, 1, 2000)
	fetched_at = frappe.utils.now()
	base_url = str((frappe.conf or {}).get("orgsync_base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
	base_url = base_url or DEFAULT_BASE_URL
	url = f"{base_url}/admin/reconcile-reports?{urlencode({'hours': hours, 'limit': limit})}"

	try:
		payload = _fetch_json(url)
		if not isinstance(payload, dict) or not isinstance(payload.get("reports"), list):
			raise ValueError("Invalid reconciliation report response")

		# Return only the report contract and derived counts, never upstream metadata or credentials.
		reports = [clean for value in payload["reports"] if (clean := _clean_report(value)) is not None]
		return {"reports": reports, "summary": _summary(reports), "fetched_at": fetched_at}
	except ValueError:
		return {
			"reports": [],
			"summary": _empty_summary(),
			"fetched_at": fetched_at,
			"service_error": _("组织同步服务返回的数据格式不正确，请稍后重试。"),
		}
	except Exception as error:
		return {
			"reports": [],
			"summary": _empty_summary(),
			"fetched_at": fetched_at,
			"service_error": _service_error(error),
		}
