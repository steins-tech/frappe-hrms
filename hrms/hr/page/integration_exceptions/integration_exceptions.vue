<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { Badge, Button, Dialog, LoadingIndicator, Select, TextInput } from "frappe-ui";

const emit = defineEmits(["title"]);
const frappe = window.frappe;
const __ = window.__;
const API = "hrms.hr.page.integration_exceptions.integration_exceptions";
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100].map((value) => ({ label: String(value), value }));
const DEFAULT_HOURS = 168;

const KIND_LABELS = {
	missing_in_hrms: "HRMS 缺失",
	suspected_duplicate: "疑似重复",
	hrms_only: "仅 HRMS 存在",
	missing_in_dingtalk_overdue: "钉钉缺失超期",
	revocation_inactive: "撤销后待处置",
	pending_adoption: "待认领",
	orphan_employee: "孤立员工",
};
const STATUS_META = {
	ACTIVE: { label: "生效中", theme: "red" },
	REVIEW: { label: "待确认", theme: "blue" },
	STALE: { label: "已过时", theme: "gray" },
	RESOLVED: { label: "已恢复", theme: "green" },
};
const SEVERITY_META = {
	ERROR: { label: "错误", theme: "red" },
	WARNING: { label: "警告", theme: "amber" },
	INFO: { label: "提示", theme: "blue" },
};
const STATUS_OPTIONS = [
	{ label: "全部状态", value: "" },
	...Object.entries(STATUS_META).map(([value, meta]) => ({ label: meta.label, value })),
];
const HOURS_OPTIONS = [
	{ label: "最近 24 小时", value: 24 },
	{ label: "最近 3 天", value: 72 },
	{ label: "最近 7 天", value: 168 },
	{ label: "最近 30 天", value: 720 },
];

const reports = ref([]);
const loading = ref(true);
const fetched_at = ref(null);
const service_error = ref("");
const request_error = ref("");
const query = ref("");
const status_filter = ref("");
const severity_filter = ref("");
const kind_filter = ref("");
const hours = ref(DEFAULT_HOURS);
const page = ref(1);
const page_size = ref(20);
const table_scroll = ref(null);
const selected = ref(null);
const detail_open = ref(false);
const copy_feedback = ref("");
let latest_request = 0;

function normalize_status(value) {
	const status = String(value || "").trim().toUpperCase();
	return STATUS_META[status] ? status : "REVIEW";
}

function status_badge(report) {
	const status = normalize_status(report.status);
	return { label: STATUS_META[status].label, theme: STATUS_META[status].theme };
}

function severity_badge(report) {
	const severity = String(report.severity || "").trim().toUpperCase();
	const meta = SEVERITY_META[severity];
	return meta ? { ...meta } : { label: severity || "未知", theme: "gray" };
}

function kind_label(value) {
	const kind = String(value || "").trim();
	return KIND_LABELS[kind] || kind || "未知类型";
}

function display_value(value) {
	if (value === null || value === undefined || value === "") return "—";
	if (typeof value === "object") {
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return String(value);
		}
	}
	return String(value);
}

function detail_text(value) {
	if (value === null || value === undefined || value === "") return "";
	return display_value(value);
}

function parse_time(value) {
	if (!value) return 0;
	const raw = String(value).trim();
	const normalized = /^\d{4}-\d{2}-\d{2} /.test(raw) ? raw.replace(" ", "T") : raw;
	const timestamp = Date.parse(normalized);
	return Number.isFinite(timestamp) ? timestamp : 0;
}

function local_date_key(value) {
	const date = value instanceof Date ? value : new Date(value);
	if (Number.isNaN(date.getTime())) return "";
	return [
		date.getFullYear(),
		String(date.getMonth() + 1).padStart(2, "0"),
		String(date.getDate()).padStart(2, "0"),
	].join("-");
}

function format_datetime(value) {
	if (!value) return "—";
	try {
		const formatted = frappe.datetime?.str_to_user?.(value);
		if (formatted && formatted !== value) return formatted;
	} catch {
		// Keep the original value when Desk cannot parse an upstream timestamp.
	}
	return display_value(value);
}

function relative_time(value) {
	const timestamp = parse_time(value);
	if (!timestamp) return "时间待核对";
	const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
	if (minutes < 1) return "刚刚";
	if (minutes < 60) return `${minutes} 分钟前`;
	const hour_count = Math.floor(minutes / 60);
	if (hour_count < 24) return `${hour_count} 小时前`;
	return `${Math.floor(hour_count / 24)} 天前`;
}

function is_employee_docname(value) {
	return typeof value === "string" && /^HR-EMP-/i.test(value.trim());
}

function report_object(report) {
	return display_value(report.dingtalkKey ?? report.id);
}

function searchable_text(report) {
	return [
		report.id,
		report.runId,
		report.kind,
		kind_label(report.kind),
		report.severity,
		report.status,
		STATUS_META[normalize_status(report.status)].label,
		report.statusReason,
		report.dingtalkKey,
		report.hrmsDocname,
		report.detail,
		report.createdAt,
	]
		.map(display_value)
		.join(" ")
		.toLowerCase();
}

const filtered_reports = computed(() => {
	const text = query.value.trim().toLowerCase();
	return reports.value
		.filter((report) => {
			const matches_status = !status_filter.value || normalize_status(report.status) === status_filter.value;
			const matches_severity =
				!severity_filter.value || String(report.severity || "").toUpperCase() === severity_filter.value;
			const matches_kind = !kind_filter.value || report.kind === kind_filter.value;
			const matches_query = !text || searchable_text(report).includes(text);
			return matches_status && matches_severity && matches_kind && matches_query;
		})
		.sort((left, right) => {
			const by_time = parse_time(right.createdAt) - parse_time(left.createdAt);
			if (by_time) return by_time;
			return String(right.id ?? "").localeCompare(String(left.id ?? ""));
		});
});

const stats = computed(() => {
	const counts = { ACTIVE: 0, REVIEW: 0, STALE: 0, RESOLVED: 0, TODAY: 0 };
	const today = local_date_key(new Date());
	for (const report of reports.value) {
		counts[normalize_status(report.status)] += 1;
		if (today && local_date_key(report.createdAt) === today) counts.TODAY += 1;
	}
	return counts;
});

const stat_cards = computed(() => [
	{
		label: __("生效中"),
		value: stats.value.ACTIVE,
		note: __("当前核对仍成立"),
		icon: "lucide-circle-alert",
		tone: "bg-surface-red-1 text-ink-red-5",
	},
	{
		label: __("待确认"),
		value: stats.value.REVIEW,
		note: __("需人工判断"),
		icon: "lucide-circle-help",
		tone: "bg-surface-blue-1 text-ink-blue-5",
	},
	{
		label: __("已过时"),
		value: stats.value.STALE,
		note: __("历史快照不再适用"),
		icon: "lucide-history",
		tone: "bg-surface-gray-2 text-ink-gray-6",
	},
	{
		label: __("已恢复"),
		value: stats.value.RESOLVED,
		note: __("差异已消失"),
		icon: "lucide-circle-check",
		tone: "bg-surface-green-1 text-ink-green-5",
	},
	{
		label: __("今日新增"),
		value: stats.value.TODAY,
		note: __("按本地自然日统计"),
		icon: "lucide-calendar-plus",
		tone: "bg-surface-blue-1 text-ink-blue-5",
	},
]);

const kind_options = computed(() => {
	const known = Object.keys(KIND_LABELS).map((value) => ({ label: KIND_LABELS[value], value }));
	const extra = [...new Set(reports.value.map((report) => report.kind).filter(Boolean))]
		.filter((value) => !KIND_LABELS[value])
		.sort()
		.map((value) => ({ label: String(value), value }));
	return [{ label: "全部问题类型", value: "" }, ...known, ...extra];
});

const severity_options = computed(() => {
	const known = Object.keys(SEVERITY_META).map((value) => ({ label: SEVERITY_META[value].label, value }));
	const extra = [...new Set(reports.value.map((report) => String(report.severity || "").trim().toUpperCase()).filter(Boolean))]
		.filter((value) => !SEVERITY_META[value])
		.sort()
		.map((value) => ({ label: value, value }));
	return [{ label: "全部级别", value: "" }, ...known, ...extra];
});

const total_pages = computed(() => Math.max(1, Math.ceil(filtered_reports.value.length / page_size.value)));
const paginated_reports = computed(() => {
	const start = (page.value - 1) * page_size.value;
	return filtered_reports.value.slice(start, start + page_size.value);
});
const page_start = computed(() => (filtered_reports.value.length ? (page.value - 1) * page_size.value + 1 : 0));
const page_end = computed(() => Math.min(page.value * page_size.value, filtered_reports.value.length));
const filters_active = computed(() =>
	Boolean(
		query.value.trim() ||
			status_filter.value ||
			severity_filter.value ||
			kind_filter.value ||
			hours.value !== DEFAULT_HOURS,
	),
);
const active_error = computed(() => request_error.value || service_error.value);
const empty_title = computed(() => {
	if (request_error.value) return __("无法读取异常报告");
	if (service_error.value) return __("组织同步服务暂时不可用");
	if (reports.value.length) return __("没有符合筛选条件的报告");
	return __("暂无异常报告");
});
const empty_description = computed(() => {
	if (active_error.value) return __("请检查服务状态后点击刷新重试。");
	if (reports.value.length) return __("试试调整搜索关键词或清空筛选条件。");
	return __("当前时间范围内没有需要处理的记录。");
});

const detail_rows = computed(() => {
	if (!selected.value) return [];
	const report = selected.value;
	return [
		{ label: __("状态"), value: STATUS_META[normalize_status(report.status)].label },
		{ label: __("状态原因"), value: display_value(report.statusReason) === "—" ? __("未提供状态原因") : display_value(report.statusReason) },
		{ label: __("runId"), value: display_value(report.runId) },
		{ label: __("钉钉标识"), value: display_value(report.dingtalkKey) },
		{ label: __("HRMS 文档"), value: display_value(report.hrmsDocname) },
		{ label: __("发生时间"), value: format_datetime(report.createdAt) },
		{ label: __("级别"), value: severity_badge(report).label },
		{ label: __("问题类型"), value: kind_label(report.kind) },
		{ label: __("类型代码"), value: display_value(report.kind) },
		{ label: __("报告 ID"), value: display_value(report.id) },
	];
});

function get_reports_payload() {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: `${API}.get_reports`,
			args: { hours: hours.value, limit: 2000 },
			type: "GET",
			callback(response) {
				resolve(response?.message ?? response ?? {});
			},
			error(error) {
				reject(error);
			},
		});
	});
}

async function load_reports() {
	const request_id = ++latest_request;
	loading.value = true;
	reports.value = [];
	service_error.value = "";
	request_error.value = "";
	page.value = 1;

	try {
		const data = await get_reports_payload();
		if (request_id !== latest_request) return;
		if (!Array.isArray(data?.reports)) throw new Error("Invalid report response");
		reports.value = data.reports.filter((report) => report && typeof report === "object");
		fetched_at.value = data.fetched_at || new Date().toISOString();
		service_error.value = data.service_error ? String(data.service_error) : "";
	} catch {
		if (request_id !== latest_request) return;
		request_error.value = __("读取异常报告失败，请确认账号权限并检查网络后重试。");
		fetched_at.value = new Date().toISOString();
	} finally {
		if (request_id === latest_request) loading.value = false;
	}
}

function clear_filters() {
	query.value = "";
	status_filter.value = "";
	severity_filter.value = "";
	kind_filter.value = "";
	hours.value = DEFAULT_HOURS;
	page.value = 1;
}

function open_detail(report) {
	selected.value = report;
	copy_feedback.value = "";
	detail_open.value = true;
}

function open_employee(docname) {
	if (is_employee_docname(docname)) frappe.set_route("Form", "Employee", docname.trim());
}

function legacy_copy(text) {
	const textarea = document.createElement("textarea");
	textarea.value = text;
	textarea.setAttribute("readonly", "");
	textarea.style.position = "fixed";
	textarea.style.opacity = "0";
	document.body.appendChild(textarea);
	textarea.select();
	const copied = document.execCommand("copy");
	textarea.remove();
	if (!copied) throw new Error("Copy failed");
}

async function copy_text(text, field) {
	if (!text) {
		frappe.show_alert({ message: __("没有可复制的内容"), indicator: "orange" });
		return;
	}
	try {
		if (window.navigator.clipboard?.writeText) {
			await window.navigator.clipboard.writeText(text);
		} else {
			legacy_copy(text);
		}
	} catch {
		try {
			legacy_copy(text);
		} catch {
			frappe.show_alert({ message: __("复制失败，请手动选择内容复制"), indicator: "red" });
			return;
		}
	}
	copy_feedback.value = field;
	frappe.show_alert({ message: __("已复制"), indicator: "green" });
}

function copy_detail() {
	if (selected.value) copy_text(detail_text(selected.value.detail), "detail");
}

function copy_run_id() {
	if (selected.value) copy_text(String(selected.value.runId ?? ""), "runId");
}

watch([query, status_filter, severity_filter, kind_filter], () => {
	page.value = 1;
});
watch(hours, (value, previous) => {
	page.value = 1;
	if (value !== previous) load_reports();
});
watch(filtered_reports, (rows) => {
	if (page.value > Math.max(1, Math.ceil(rows.length / page_size.value))) page.value = 1;
});
watch(page_size, () => {
	page.value = 1;
});
watch([page, page_size, query, status_filter, severity_filter, kind_filter], async () => {
	await nextTick();
	table_scroll.value?.scrollTo({ top: 0, left: 0 });
});

onMounted(() => {
	emit("title", __("异常报告"));
	load_reports();
});
</script>

<template>
	<div
		class="mx-auto flex h-full min-h-0 w-full max-w-[1600px] flex-col gap-4 overflow-hidden p-4 text-ink-gray-8 sm:gap-5 sm:p-6"
		role="region"
		:aria-label="__('异常报告内容')"
	>
		<header class="flex shrink-0 flex-col justify-between gap-4 sm:flex-row sm:items-start">
			<div class="min-w-0">
				<div class="flex flex-wrap items-center gap-2">
					<h1 class="text-2xl font-semibold tracking-tight text-ink-gray-8">{{ __("异常报告") }}</h1>
					<Badge theme="gray" :label="__('只读')" />
				</div>
				<p class="mt-1.5 text-sm text-ink-gray-6">{{ __("查看钉钉与 HRMS 员工对账差异，供运营人员核查。") }}</p>
				<p class="mt-2 text-xs text-ink-gray-5">
					{{ __("最后刷新时间：{0}", [format_datetime(fetched_at)]) }}
					<span aria-hidden="true"> · </span>
					{{ __("共 {0} 条记录", [reports.length]) }}
				</p>
			</div>
			<Button :loading="loading" :disabled="loading" @click="load_reports">
				<template #prefix>
					<span class="lucide-refresh-cw size-4" aria-hidden="true" />
				</template>
				{{ __("刷新") }}
			</Button>
		</header>

		<section
			class="flex shrink-0 snap-x snap-mandatory gap-3 overflow-x-auto pb-1 md:grid md:grid-cols-3 md:overflow-visible md:pb-0 xl:grid-cols-5"
			:aria-label="__('异常统计')"
		>
			<article
				v-for="card in stat_cards"
				:key="card.label"
				class="min-w-[160px] shrink-0 snap-start rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-4 shadow-sm md:min-w-0"
			>
				<div class="flex items-center justify-between gap-3">
					<p class="text-sm font-medium text-ink-gray-7">{{ card.label }}</p>
					<span class="grid size-8 shrink-0 place-items-center rounded-md" :class="card.tone">
						<span :class="card.icon" class="size-4" aria-hidden="true" />
					</span>
				</div>
				<p class="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-ink-gray-8">{{ card.value }}</p>
				<p class="mt-1 text-xs text-ink-gray-5">{{ card.note }}</p>
			</article>
		</section>

		<div
			v-if="active_error"
			role="alert"
			class="flex shrink-0 items-start gap-3 rounded-lg border border-outline-red-1 bg-surface-red-1 p-3 text-sm text-ink-red-4"
		>
			<span class="lucide-circle-alert mt-0.5 size-4 shrink-0" aria-hidden="true" />
			<div class="min-w-0">
				<p class="font-medium">{{ __("暂时无法获取异常报告") }}</p>
				<p class="mt-0.5 break-words text-ink-red-3">{{ active_error }}</p>
			</div>
		</div>

		<section class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-elevation-1 shadow-sm" :aria-label="__('异常记录')">
			<div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-outline-gray-2 px-4 py-3">
				<div class="flex items-center gap-2">
					<h2 class="text-base font-semibold text-ink-gray-8">{{ __("异常记录") }}</h2>
					<Badge theme="gray" :label="String(filtered_reports.length)" />
				</div>
				<p class="flex items-center gap-1.5 text-xs text-ink-gray-5">
					<span class="lucide-arrow-down-wide-narrow size-3.5" aria-hidden="true" />
					{{ __("按发生时间倒序") }}
				</p>
			</div>

			<div class="flex shrink-0 flex-nowrap items-end gap-3 overflow-x-auto border-b border-outline-gray-2 px-4 py-3 md:flex-wrap md:overflow-visible">
				<label class="flex min-w-[260px] flex-none basis-64 flex-col gap-1.5 text-xs font-medium text-ink-gray-6 md:min-w-0 md:flex-1">
					<span>{{ __("搜索") }}</span>
					<TextInput
						v-model="query"
						type="search"
						:placeholder="__('搜索员工标识、问题摘要或 runId')"
						autocomplete="off"
					>
						<template #prefix>
							<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
						</template>
					</TextInput>
				</label>

				<label class="flex min-w-[140px] flex-none basis-32 flex-col gap-1.5 text-xs font-medium text-ink-gray-6 md:min-w-0 md:flex-1">
					<span>{{ __("状态") }}</span>
					<Select v-model="status_filter" :options="STATUS_OPTIONS" :aria-label="__('状态筛选')" />
				</label>

				<label class="flex min-w-[140px] flex-none basis-32 flex-col gap-1.5 text-xs font-medium text-ink-gray-6 md:min-w-0 md:flex-1">
					<span>{{ __("级别") }}</span>
					<Select v-model="severity_filter" :options="severity_options" :aria-label="__('级别筛选')" />
				</label>

				<label class="flex min-w-[160px] flex-none basis-40 flex-col gap-1.5 text-xs font-medium text-ink-gray-6 md:min-w-0 md:flex-1">
					<span>{{ __("问题类型") }}</span>
					<Select v-model="kind_filter" :options="kind_options" :aria-label="__('问题类型筛选')" />
				</label>

				<label class="flex min-w-[150px] flex-none basis-36 flex-col gap-1.5 text-xs font-medium text-ink-gray-6 md:min-w-0 md:flex-1">
					<span>{{ __("时间范围") }}</span>
					<Select v-model="hours" :options="HOURS_OPTIONS" :aria-label="__('时间范围')" />
				</label>

				<Button class="shrink-0" variant="ghost" :disabled="!filters_active" @click="clear_filters">{{ __("清空筛选") }}</Button>
			</div>

			<div v-if="loading" class="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-sm text-ink-gray-5">
				<LoadingIndicator class="size-6 text-ink-gray-5" />
				<p>{{ __("正在读取异常报告…") }}</p>
			</div>

			<div ref="table_scroll" v-else class="min-h-0 flex-1 overflow-auto">
				<table class="w-full min-w-[1160px] table-fixed border-collapse text-sm">
					<caption class="sr-only">{{ __("异常报告列表，按发生时间倒序排列。") }}</caption>
					<thead class="sticky top-0 z-10 bg-surface-gray-1 text-xs text-ink-gray-5">
						<tr>
							<th scope="col" class="w-28 px-3 py-2.5 text-start font-medium">{{ __("状态") }}</th>
							<th scope="col" class="w-24 px-3 py-2.5 text-start font-medium">{{ __("级别") }}</th>
							<th scope="col" class="w-40 px-3 py-2.5 text-start font-medium">{{ __("问题类型") }}</th>
							<th scope="col" class="w-48 px-3 py-2.5 text-start font-medium">{{ __("对象 / 钉钉标识") }}</th>
							<th scope="col" class="w-44 px-3 py-2.5 text-start font-medium">{{ __("HRMS 文档") }}</th>
							<th scope="col" class="px-3 py-2.5 text-start font-medium">{{ __("摘要") }}</th>
							<th scope="col" class="w-40 px-3 py-2.5 text-start font-medium">{{ __("发生时间") }}</th>
							<th scope="col" class="w-24 px-3 py-2.5 text-start font-medium">{{ __("操作") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(report, index) in paginated_reports"
							:key="report.id ?? `${report.runId}-${report.createdAt}-${report.kind}-${index}`"
							class="border-t border-outline-gray-2 transition-colors hover:bg-surface-gray-1"
						>
							<td class="px-3 py-3 align-top"><Badge v-bind="status_badge(report)" /></td>
							<td class="px-3 py-3 align-top"><Badge v-bind="severity_badge(report)" /></td>
							<td class="px-3 py-3 align-top">
								<p class="truncate font-medium text-ink-gray-8" :title="kind_label(report.kind)">{{ kind_label(report.kind) }}</p>
								<p v-if="KIND_LABELS[report.kind]" class="mt-0.5 truncate font-mono text-[11px] text-ink-gray-5" :title="report.kind">{{ report.kind }}</p>
							</td>
							<td class="px-3 py-3 align-top">
								<p class="truncate font-mono text-xs text-ink-gray-7" :title="report_object(report)">{{ report_object(report) }}</p>
							</td>
							<td class="px-3 py-3 align-top">
								<button
									v-if="is_employee_docname(report.hrmsDocname)"
									type="button"
									class="max-w-full truncate text-start font-mono text-xs text-ink-blue-5 hover:underline"
									:title="__('打开员工')"
									@click="open_employee(report.hrmsDocname)"
								>
									{{ report.hrmsDocname }}
								</button>
								<span v-else class="block truncate font-mono text-xs text-ink-gray-6" :title="display_value(report.hrmsDocname)">
									{{ display_value(report.hrmsDocname) }}
								</span>
							</td>
							<td class="px-3 py-3 align-top">
								<p class="line-clamp-2 break-words text-ink-gray-7" :title="detail_text(report.detail)">
									{{ detail_text(report.detail) || __("无摘要") }}
								</p>
							</td>
							<td class="px-3 py-3 align-top">
								<p class="text-xs text-ink-gray-7">{{ format_datetime(report.createdAt) }}</p>
								<p class="mt-0.5 text-[11px] text-ink-gray-5">{{ relative_time(report.createdAt) }}</p>
							</td>
							<td class="px-3 py-3 align-top">
								<Button variant="subtle" :label="__('查看')" @click="open_detail(report)" />
							</td>
						</tr>
						<tr v-if="!paginated_reports.length">
							<td colspan="8" class="px-4 py-16 text-center">
								<div class="mx-auto flex max-w-sm flex-col items-center">
									<span class="lucide-inbox mb-3 size-10 text-ink-gray-4" aria-hidden="true" />
									<p class="text-base font-medium text-ink-gray-8">{{ empty_title }}</p>
									<p class="mt-1 text-sm text-ink-gray-5">{{ empty_description }}</p>
									<Button v-if="filters_active" class="mt-4" variant="outline" :label="__('清空筛选')" @click="clear_filters" />
								</div>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<footer class="flex shrink-0 flex-col justify-between gap-3 border-t border-outline-gray-2 px-4 py-3 sm:flex-row sm:items-center">
				<p class="text-xs tabular-nums text-ink-gray-5">
					{{ __("显示 {0}–{1} 条，共 {2} 条", [page_start, page_end, filtered_reports.length]) }}
				</p>
				<div class="flex flex-wrap items-center justify-end gap-3">
					<label class="flex items-center gap-2 text-xs text-ink-gray-5">
						<span>{{ __("每页") }}</span>
						<Select v-model="page_size" :options="PAGE_SIZE_OPTIONS" :aria-label="__('每页条数')" />
						<span>{{ __("条") }}</span>
					</label>
					<nav class="flex items-center gap-2" :aria-label="__('异常报告分页')">
						<Button variant="outline" :disabled="page <= 1" :label="__('上一页')" @click="page -= 1" />
						<span class="min-w-16 text-center text-xs tabular-nums text-ink-gray-6">{{ page }} / {{ total_pages }}</span>
						<Button variant="outline" :disabled="page >= total_pages" :label="__('下一页')" @click="page += 1" />
					</nav>
				</div>
			</footer>
		</section>

		<p class="hidden shrink-0 text-xs text-ink-gray-5 sm:block">{{ __("当前页面仅提供查看、筛选和复制。异常处置请在同步服务或 HRMS 中完成。") }}</p>

		<Dialog v-model="detail_open" :title="__('异常详情')">
			<template v-if="selected" #default>
				<div class="max-h-[65vh] space-y-5 overflow-y-auto pe-1">
					<div class="flex flex-wrap items-center gap-2">
						<Badge v-bind="status_badge(selected)" />
						<Badge v-bind="severity_badge(selected)" />
						<span class="text-sm font-medium text-ink-gray-8">{{ kind_label(selected.kind) }}</span>
					</div>

					<dl class="divide-y divide-outline-gray-2 rounded-md border border-outline-gray-2">
						<div v-for="row in detail_rows" :key="row.label" class="grid grid-cols-1 gap-1 px-3 py-2.5 sm:grid-cols-[120px_minmax(0,1fr)] sm:gap-3">
							<dt class="text-xs font-medium text-ink-gray-5">{{ row.label }}</dt>
							<dd class="min-w-0 break-words font-mono text-xs text-ink-gray-8">{{ row.value }}</dd>
						</div>
					</dl>

					<section>
						<h3 class="mb-2 text-sm font-medium text-ink-gray-8">{{ __("完整 detail") }}</h3>
						<pre class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3 font-mono text-xs text-ink-gray-7">{{ detail_text(selected.detail) || __("无详情") }}</pre>
					</section>
				</div>
			</template>

			<template v-if="selected" #actions>
				<div class="flex flex-wrap justify-end gap-2">
					<Button variant="subtle" :label="copy_feedback === 'detail' ? __('详情已复制') : __('复制详情')" @click="copy_detail" />
					<Button variant="subtle" :label="copy_feedback === 'runId' ? __('runId 已复制') : __('复制 runId')" @click="copy_run_id" />
					<Button v-if="is_employee_docname(selected.hrmsDocname)" :label="__('打开员工')" @click="open_employee(selected.hrmsDocname)" />
					<Button :label="__('关闭')" @click="detail_open = false" />
				</div>
			</template>
		</Dialog>
	</div>
</template>
