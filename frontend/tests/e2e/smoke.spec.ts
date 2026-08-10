import { expect, test } from "@playwright/test";

test("shows the CA-Agent login page", async ({ page }) => {
  await page.goto("/auth/login");
  await expect(page.getByRole("heading", { name: "CI-Agent" })).toBeVisible();
  await expect(page.getByLabel("邮箱")).toBeVisible();
  await expect(page.getByLabel("密码")).toBeVisible();
});
