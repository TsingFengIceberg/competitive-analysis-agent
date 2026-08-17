import { expect, test } from "@playwright/test";

const draftBrief = {
  version: 1,
  revision: 1,
  objective: "选择适合团队的 AI 编程工具",
  target_products: [],
  audience: "product",
  market_scope: "Global / unspecified",
  time_range: {
    mode: "last_12_months",
    label: "最近12个月",
    start: null,
    end: null,
  },
  dimensions: [
    { id: "features", label: "功能与体验", weight: 0.5 },
    { id: "pricing", label: "定价与商业模式", weight: 0.5 },
  ],
  complexity: "standard",
  evidence_policy: "official_preferred",
  output_focus: ["关键差异", "可执行建议"],
  assumptions: [],
  inferred_fields: ["market_scope", "time_range"],
  readiness: "needs_confirmation",
  ambiguities: [
    {
      field: "target_products",
      question: "请确认具体竞品名单。",
      required: true,
    },
  ],
  confidence: 0.5,
  confirmation_source: null,
  confirmed_at: null,
};

test.describe("Analysis Brief confirmation", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/competition/me", (route) =>
      route.fulfill({ json: { authenticated: true, config_mode: "file" } }),
    );
    await page.route("**/api/competition/analyze", async (route) => {
      expect(route.request().postDataJSON().confirmation_mode).toBe("always");
      await route.fulfill({
        json: {
          thread_id: "comp-e2e",
          status: "awaiting_confirmation",
          analysis_brief: draftBrief,
        },
      });
    });
    await page.route("**/api/competition/report/comp-e2e", (route) =>
      route.fulfill({
        json: {
          thread_id: "comp-e2e",
          status: "awaiting_confirmation",
          query: "最好的 AI 编程工具有哪些？",
          title: "新建分析 1",
          report_data: null,
          analysis_brief: draftBrief,
          phases: [],
          token_usage: [],
          history_count: 0,
        },
      }),
    );
    await page.route("**/api/competition/comp-e2e/confirm", async (route) => {
      const payload = route.request().postDataJSON();
      expect(payload.expected_revision).toBe(1);
      expect(payload.brief.target_products).toEqual(["Cursor", "Copilot"]);
      await route.fulfill({
        json: {
          thread_id: "comp-e2e",
          status: "running",
          analysis_brief: {
            ...draftBrief,
            revision: 2,
            target_products: ["Cursor", "Copilot"],
            readiness: "ready",
            confirmation_source: "user",
          },
        },
      });
    });
    await page.route("**/api/competition/stream/comp-e2e", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: values\ndata: {"status":"running"}\n\n',
      }),
    );
  });

  test("edits the same thread and starts only after confirmation", async ({
    page,
  }) => {
    const hydrated = page.waitForResponse("**/api/competition/me");
    await page.goto("/competition/new");
    await hydrated;
    await page
      .getByPlaceholder(/输入竞品分析请求/)
      .fill("最好的 AI 编程工具有哪些？");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(
      page.getByRole("heading", { name: "请确认分析范围" }),
    ).toBeVisible();
    await page.getByLabel("竞品（每行一个）").fill("Cursor\nCopilot");
    await page.getByRole("button", { name: "确认并开始" }).click();
    await expect(page.getByText("分析范围")).toBeVisible();
  });

  test("renders the editor on a narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const hydrated = page.waitForResponse("**/api/competition/me");
    await page.goto("/competition/new");
    await hydrated;
    await page
      .getByPlaceholder(/输入竞品分析请求/)
      .fill("最好的 AI 编程工具有哪些？");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(
      page.getByRole("heading", { name: "请确认分析范围" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "确认并开始" }),
    ).toBeVisible();
  });
});
