import { expect, test } from "@playwright/test";

const report = {
  persona: "pm",
  title: "Cursor vs Copilot 竞品分析报告",
  generated_at: "2026-08-14T10:00:00Z",
  products: ["Cursor", "Copilot"],
  sections: [
    { id: "sec-executive-summary", title: "执行摘要", content: "Cursor 优势 [1]", content_type: "text", source_ids: ["1"], chart_path: null, subsections: null },
    { id: "sec-comparison-matrix", title: "对比矩阵", content: "| 产品 | 功能 |\n|---|---|\n| Cursor | 5 |", content_type: "table", source_ids: ["1"], chart_path: null, subsections: null },
  ],
  traceability_map: { "1": { url: "https://example.com/source", timestamp: "2026-08-14T09:00:00Z", confidence: 0.9, title: "官方资料", product: "Cursor", source_type: "official", collected_at: "2026-08-14T09:00:00Z", published_at: "2026-08-10", publication_date_status: "known" } },
  quality_summary: {},
  forecast: null,
  metrics: { coverage: 1, trace_completeness: 1 },
  quality_gate: { schema_version: 1, status: "warning", generated_at: "2026-08-14T10:00:00Z", policy: "official_preferred", blocking_count: 0, warning_count: 1, dimensions: [{ dimension_id: "features", label: "功能与体验", selected: true, products_total: 2, products_covered: ["Cursor"], missing_products: ["Copilot"], data_point_count: 1, source_domain_count: 1, coverage_ratio: 0.5, status: "blocked", issue_ids: ["coverage-features-1"] }], sources: { total: 1, official: 1, strong: 1, moderate: 0, weak: 0, unknown_publication_date: 0, outside_requested_range: 0 }, claims: { total: 1, multi_source: 0, single_source: 1, unsupported: 0 }, issues: [{ id: "warning-1", level: "warning", severity: "minor", type: "single_source", check_method: "comparison_claim", description: "声明只有单一来源", remediation: "补充独立来源", dimension_ids: [], product_names: [], data_point_ids: [], citation_ids: ["1"], section_ids: ["sec-comparison-matrix"] }], rework: { review_round: 1, reviewer_notes: "", improvement_ratio: null, repair_delta: null, current_round_metrics: null, previous_round_metrics: null } },
};

const history = [{ version: 1, parent_version: null, action: "initial", created_at: "2026-08-14T10:00:00Z", report_data: report }];

test.describe("Research workbench", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/competition/me", (route) => route.fulfill({ json: { authenticated: true, config_mode: "file" } }));
    await page.route("**/api/competition/report/workbench-thread", (route) => route.fulfill({ json: { thread_id: "workbench-thread", status: "completed", query: "Cursor vs Copilot", title: report.title, report_data: report, metrics: report.metrics, history_count: 1, token_usage: [], phases: [] } }));
    await page.route("**/api/competition/report/workbench-thread/history", (route) => route.fulfill({ json: { history, count: 1 } }));
    await page.route("**/api/competition/report/workbench-thread/trace", (route) => route.fulfill({ json: { thread_id: "workbench-thread", generations: [{ version: 0, generation_id: "gen-1", report_version: 1, parent_report_version: null, association: "exact", action: "initial", label: "初始分析", phases: [{ phase_key: "writer", label: "报告生成", icon: "📝", agent_name: "Writer", tokens: 12, duration_ms: 100, status: "completed", start_time: null, end_time: null, content: {}, details: [], json_output: { title: report.title } }] }], dag: { nodes: [], edges: [] }, current_version: 1 } }));
  });

  test("opens the three-pane desktop workbench and source inspector", async ({ page }) => {
    await page.goto("/competition/workbench-thread");
    await expect(page.getByRole("button", { name: "研究工作台" })).toBeVisible();
    await page.getByRole("button", { name: "研究工作台" }).click();
    await expect(page.getByText("研究工作台")).toBeVisible();
    await expect(page.getByText("质量门禁有警告")).toBeVisible();
    await page.getByRole("button", { name: "来源" }).last().click();
    await expect(page.getByText("https://example.com/source")).toBeVisible();
  });

  test("uses one-pane tabs on mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/competition/workbench-thread");
    await page.getByRole("button", { name: "研究工作台" }).click();
    await expect(page.getByRole("button", { name: "版本" })).toBeVisible();
    await page.getByRole("button", { name: "质量" }).first().click();
    await expect(page.getByText("维度覆盖")).toBeVisible();
  });
});
