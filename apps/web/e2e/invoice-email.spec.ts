/**
 * Invoice delivery journeys — the full chain, no mocks:
 * console download → PDF endpoint, finalize → outbox → worker → SMTP (MailHog),
 * pay → receipt email with the PDF attached.
 *
 * Requires: the arq worker running (outbox dispatch every 5s) and an SMTP
 * sink (MailHog) reachable at MAILHOG_API_URL. The e2e workflow provides
 * both; locally: docker compose --profile extras up -d mailhog + worker.
 */
import {
  test,
  expect,
  createStackContext,
  loginConsole,
  api,
  waitForEmail,
  API_URL,
} from "./fixtures";

test.describe("invoice delivery", () => {
  test("console downloads the framework-rendered PDF", async ({ page, request }) => {
    const ctx = await createStackContext(request, "invpdf");
    const client = api(request, ctx);

    // Paid plan so the invoice has a line + finalize issues a number
    await client.post("/v1/subscription/change", { plan_key: "pro" });
    const invoice = (await (
      await client.post("/v1/billing/invoices/draft", {})
    ).json()) as { id: string };
    const finalized = (await (
      await client.post(`/v1/billing/invoices/${invoice.id}/finalize`, {})
    ).json()) as { number: string };
    expect(finalized.number).toMatch(/^INV-/);

    // API-level: bytes are a real PDF with the invoice number in the filename
    const pdfRes = await request.get(`${API_URL}/v1/billing/invoices/${invoice.id}/pdf`, {
      headers: { Authorization: `Bearer ${ctx.accessToken}`, "X-Org-Id": ctx.orgId },
    });
    expect(pdfRes.ok(), "pdf endpoint").toBeTruthy();
    expect(pdfRes.headers()["content-type"]).toContain("application/pdf");
    const disposition = pdfRes.headers()["content-disposition"] ?? "";
    expect(disposition).toContain(finalized.number);
    const buf = await pdfRes.body();
    expect(Buffer.from(buf).subarray(0, 5).toString()).toBe("%PDF-");

    // UI-level: the billing page exposes a per-row download that fires a download
    await loginConsole(page, ctx);
    await page.goto("/dashboard/billing");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /download invoice pdf/i }).first().click();
    const dl = await download;
    expect(dl.suggestedFilename()).toContain(finalized.number);
  });

  test("finalize emails the invoice with the PDF attached", async ({ request }) => {
    const ctx = await createStackContext(request, "invmail");
    const client = api(request, ctx);

    // Recipient: org settings.billing_email (no billing-customer on this path)
    const recipient = `e2e-${ctx.orgSlug}-ap@example.com`;
    const patch = await request.patch(`${API_URL}/v1/orgs/current`, {
      headers: { Authorization: `Bearer ${ctx.accessToken}`, "X-Org-Id": ctx.orgId },
      data: { settings: { billing_email: recipient } },
    });
    expect(patch.ok(), `set billing_email: ${patch.status()}`).toBeTruthy();

    await client.post("/v1/subscription/change", { plan_key: "pro" });
    const invoice = (await (
      await client.post("/v1/billing/invoices/draft", {})
    ).json()) as { id: string; total_cents: number };
    const finalized = (await (
      await client.post(`/v1/billing/invoices/${invoice.id}/finalize`, {})
    ).json()) as { number: string; total_cents: number };
    expect(finalized.number).toMatch(/^INV-/);

    // Outbox → worker (≤5s cron) → SMTP. Poll MailHog for the delivery.
    // Match recipient too: invoice numbers are per-org (many orgs share 0001).
    const email = await waitForEmail(
      request,
      (m) => m.to === recipient && m.subject.includes(finalized.number),
    );
    expect(email.to).toContain("ap@example.com");
    expect(email.subject).toMatch(/^Invoice /);
    // Attachment: base64 application/pdf part decoding to %PDF-
    expect(email.raw).toContain("application/pdf");
    expect(email.raw).toContain(`invoice-${finalized.number}.pdf`);
    const flat = email.raw.replace(/\r\n/g, "\n");
    const b64 = flat.match(
      /Content-Type: application\/pdf\nContent-Transfer-Encoding: base64\nContent-Disposition: attachment; filename="invoice-[^"]+\.pdf"\nMIME-Version: 1\.0\n\n([A-Za-z0-9+/=\n]+)/,
    )?.[1];
    expect(b64, "base64 PDF part present").toBeTruthy();
    const decoded = Buffer.from((b64 ?? "").replace(/\n/g, ""), "base64");
    expect(decoded.subarray(0, 5).toString()).toBe("%PDF-");
  });

  test("recording payment emails a paid receipt", async ({ request }) => {
    const ctx = await createStackContext(request, "invpaid");
    const client = api(request, ctx);
    const recipient = `e2e-${ctx.orgSlug}-ap@example.com`;

    await request.patch(`${API_URL}/v1/orgs/current`, {
      headers: { Authorization: `Bearer ${ctx.accessToken}`, "X-Org-Id": ctx.orgId },
      data: { settings: { billing_email: recipient } },
    });

    await client.post("/v1/subscription/change", { plan_key: "pro" });
    const invoice = (await (
      await client.post("/v1/billing/invoices/draft", {})
    ).json()) as { id: string; total_cents: number };
    const finalized = (await (
      await client.post(`/v1/billing/invoices/${invoice.id}/finalize`, {})
    ).json()) as { number: string; total_cents: number };

    const paid = (await (
      await client.post(`/v1/billing/invoices/${invoice.id}/pay`, {
        amount_cents: finalized.total_cents,
        reference: "e2e-bank-transfer",
      })
    ).json()) as { status: string };
    expect(paid.status).toBe("paid");

    // The finalize email may also arrive — match strictly on the paid form.
    const email = await waitForEmail(
      request,
      (m) => m.to === recipient && m.subject === `Paid: Invoice ${finalized.number}`,
    );
    expect(email.subject).toContain(finalized.number);
    expect(email.raw).toContain("application/pdf");
  });
});
