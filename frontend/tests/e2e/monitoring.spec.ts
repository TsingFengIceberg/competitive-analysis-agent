import { expect, test } from "@playwright/test";

const schedule = {
  schedule_id: "schedule-1",
  name: "AI 编程工具观察",
  products: ["Cursor", "Codex"],
  dimensions: ["features", "pricing"],
  market_scope: "Global",
  daily_times: ["09:00"],
  interval_minutes: null,
  enabled: true,
  next_run_at: "2026-08-24T01:00:00Z",
  last_run_at: "2026-08-23T01:00:00Z",
  last_success_at: "2026-08-23T01:00:01Z",
  last_failure_at: null,
  last_status: "skipped",
  last_error: null,
  last_skip_reason: "no_material_change",
};

const rule = {
  rule_id: "rule-1",
  name: "关键定价变化",
  event_types: ["fact_changed"],
  products: ["Cursor"],
  dimensions: ["pricing"],
  min_severity: "major",
  cooldown_minutes: 60,
  quiet_start: "23:00",
  quiet_end: "08:00",
  timezone: "Asia/Shanghai",
  delivery_mode: "immediate",
  enabled: true,
};

test.describe("Competition monitoring workspace", () => {
  let lastScheduleUpdate: Record<string, unknown> | null;
  let currentUser: Record<string, unknown>;

  test.beforeEach(async ({ page }) => {
    lastScheduleUpdate = null;
    currentUser = { authenticated: true, config_mode: "file" };
    await page.route("**/api/competition/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname;
      if (path.endsWith("/me")) {
        return route.fulfill({ json: currentUser });
      }
      if (path.endsWith("/db-history")) {
        return route.fulfill({ json: { history: [] } });
      }
      if (path.endsWith("/observation/runtime")) {
        return route.fulfill({
          json: {
            running: true,
            last_tick_at: "2026-08-23T02:00:00Z",
            last_error: null,
          },
        });
      }
      if (path.endsWith("/observation/schedules")) {
        return route.fulfill({ json: { schedules: [schedule] } });
      }
      if (path.endsWith("/observation/runs")) {
        return route.fulfill({
          json: {
            runs: [
              {
                run_id: "run-1",
                schedule_id: schedule.schedule_id,
                schedule_name: schedule.name,
                started_at: "2026-08-23T01:00:00Z",
                finished_at: "2026-08-23T01:00:01Z",
                status: "skipped",
                summary: { material_changes: 0 },
                error: null,
                skip_reason: "no_material_change",
              },
            ],
          },
        });
      }
      if (path.endsWith("/intelligence/changes")) {
        return route.fulfill({
          json: {
            changes: [
              {
                change_id: "change-1",
                item_key: "cursor-price",
                product: "Cursor",
                dimension: "pricing",
                source_domain: "cursor.com",
                change_type: "fact_changed",
                material: true,
                old_value: "$20",
                new_value: "$25",
                detected_at: "2026-08-23T01:00:00Z",
                payload: { source_url: "https://cursor.com/pricing" },
              },
            ],
          },
        });
      }
      if (path.endsWith("/alerts/rules")) {
        return route.fulfill({ json: { rules: [rule] } });
      }
      if (path.endsWith("/alerts/events")) {
        return route.fulfill({
          json: {
            events: [
              {
                event_id: "event-1",
                event_type: "fact_changed",
                severity: "major",
                title: "Cursor 定价发生变化",
                message: "Pro 价格从 $20 调整到 $25",
                status: "pending",
                last_seen_at: "2026-08-23T01:00:00Z",
                suppressed_reason: null,
              },
            ],
          },
        });
      }
      if (path.endsWith(`/observation/schedules/${schedule.schedule_id}`)) {
        if (request.method() === "PUT") {
          lastScheduleUpdate = request.postDataJSON();
          return route.fulfill({
            json: {
              ok: true,
              schedule: { ...schedule, ...lastScheduleUpdate },
            },
          });
        }
        return route.fulfill({ json: { ok: true } });
      }
      if (path.endsWith("/alerts/dispatch")) {
        return route.fulfill({
          json: { ok: true, deliveries: [{ status: "sent" }] },
        });
      }
      return route.fulfill({ status: 404, json: { detail: "Not mocked" } });
    });
  });

  test("shows schedules, changes, alerts, and operational actions", async ({
    page,
  }) => {
    await page.goto("/competition/monitoring");

    await expect(page.getByRole("heading", { name: "竞品观察" })).toBeVisible();
    await expect(page.getByText("调度运行中")).toBeVisible();
    await expect(page.getByText("AI 编程工具观察").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "运行历史" })).toBeVisible();

    await page.getByRole("button", { name: "暂停任务" }).click();
    await expect.poll(() => lastScheduleUpdate?.enabled).toBe(false);

    await page.getByRole("tab", { name: "变化记录" }).click();
    await expect(page.getByText("$20")).toBeVisible();
    await expect(page.getByRole("link", { name: "来源" })).toHaveAttribute(
      "href",
      "https://cursor.com/pricing",
    );

    await page.getByRole("tab", { name: "告警中心" }).click();
    await expect(page.getByText("关键定价变化")).toBeVisible();
    await expect(page.getByText("Cursor 定价发生变化")).toBeVisible();
    await page.getByRole("button", { name: "投递待发告警" }).click();
  });

  test("keeps management dialogs usable on a mobile viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/competition/monitoring");
    await page.getByRole("button", { name: "编辑任务" }).click();

    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: "编辑观察任务" }),
    ).toBeVisible();
    await expect(dialog.getByRole("textbox", { name: "任务名称" })).toHaveValue(
      "AI 编程工具观察",
    );
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    );
    expect(overflow).toBe(false);
  });

  test("allows the default debug user in file mode", async ({ page }) => {
    currentUser = {
      authenticated: false,
      config_mode: "file",
      user_id: "default",
    };
    await page.goto("/competition/monitoring");

    await expect(page).toHaveURL(/\/competition\/monitoring$/);
    await expect(page.getByRole("heading", { name: "竞品观察" })).toBeVisible();
    await expect(page.getByText("File 调试模式")).toBeVisible();
    await expect(page.getByRole("button", { name: "退出" })).toHaveCount(0);
  });
});
