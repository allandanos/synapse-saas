# Notifications

Email delivery rides the transactional outbox: a mutation commits the event,
the worker sends the email. An SMTP outage delays email; it never loses it and
never fails the original request.

## Architecture

```
invite / forgot-password
        │ same tx
        ▼
  outbox_events ──► worker dispatch ──► handle_event() ──► SmtpNotifier ──► SMTP relay
                                                └────────► (also fans out webhooks)
```

## Configuration

```bash
SYNAPSE_NOTIFIER=smtp                # smtp | noop (noop is implied when no host is set)
SYNAPSE_SMTP_HOST=smtp.example.com   # unset ⇒ emails are logged, not sent
SYNAPSE_SMTP_PORT=587
SYNAPSE_SMTP_FROM=noreply@example.com
SYNAPSE_SMTP_TLS=starttls            # none (MailHog) | starttls (587) | ssl (465)
SYNAPSE_SMTP_USERNAME=…              # AUTH is refused over a plaintext connection
SYNAPSE_SMTP_PASSWORD=…
```

Any real relay (SES, Postmark, Mailgun, Google Workspace) is `starttls` or
`ssl` plus credentials. Credentials are only ever sent after the channel is
secured; `tls=none` with a username fails fast instead of leaking them.

Local dev: `docker compose --profile extras up` runs MailHog on
http://localhost:8025 — set `SYNAPSE_SMTP_HOST=localhost SYNAPSE_SMTP_PORT=1025`
and read every sent email in its UI.

## Emails today

| Event | Recipient | Content |
|---|---|---|
| `member.invited` | invitee | org name + one-time acceptance link (`/register?invite=…`) |
| `user.password_reset_link` | account owner | 30-minute reset link (`/reset-password?reset=…`) |

Unknown events are ignored — email is opt-in per event type. Soft/hard usage
limits currently go to audit + webhooks; org billing-contact routing is the
next refinement.

## Security properties (tested)

- **Tokens cross no persistence boundary in plaintext** — the outbox payload
  carries the token to the email layer; the database stores only the SHA-256
  hash, and the outbox row is marked published after dispatch
- **Opaque requests** — forgot-password returns 202 for unknown emails and
  queues *no* email; the response reveals nothing
- **Fail-soft** — SMTP down logs `email_send_failed` and moves on; dispatch
  survives, the event retries via the outbox
- **No new dependency** — stdlib `smtplib` via `asyncio.to_thread`

## Extending

Add a handler in `notifications/handlers.py`:

```python
elif event_type == "subscription.past_due":
    await notifier.send(to=owner_email, subject="…", body="…")
```

Swap the transport by implementing the `Notifier` protocol (it carries
`attachments`, so invoice PDFs work on any transport) and returning it from
`get_notifier()` — the handlers and worker wiring don't change. `NoopNotifier`
is what runs when no SMTP host is configured or `SYNAPSE_NOTIFIER=noop`.

Emails are sent **after** the outbox dispatch commits: a worker crash or retry
cannot resend the same invite or invoice. `usage.soft_limit_reached` mails the
org's billing contact (billing customer email → `settings.billing_email` →
the owner).
