---
title: Mailing
---

<!-- =========================================================
VODUM Docs - Mailing
Dark themed markdown with subtle badges & callouts
========================================================= -->

<div align="left">

# 📧 Mailing

<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
SMTP • Templates • Campaigns • Notifications
</span>

<br><br>

The **Mailing** section allows you to configure **email sending**, manage
**notification templates**, and create **custom campaigns**.

Mailing is used to:
- notify users about subscription expiration
- send reminders
- inform users when access is suspended
- send manual or campaign emails

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

</div>

## 🔌 Mailing activation

At the top of the page, you can **enable or disable mailing globally**.

- **Disabled**:  
  - SMTP configuration is ignored  
  - no emails are sent  
  - campaigns and templates are inactive  

- **Enabled**:  
  - SMTP configuration becomes active  
  - tasks can send emails  
  - campaigns and templates can be used  

> ⚠️ Mailing must be enabled for any email-related feature to work.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## ⚙️ SMTP configuration

The **Configuration SMTP** tab is used to configure how VODUM sends emails.

### SMTP provider

You can select:
- a **custom SMTP provider**
- or (depending on configuration) predefined providers

For a custom SMTP server, you must provide:
- **SMTP host**
- **SMTP port** (typically 465 or 587)
- **TLS / SSL option**
- **SMTP username**
- **SMTP password**
- **Sender email address**

> 🔐 SMTP credentials are stored securely and used only for sending emails.

---

### TLS / SSL

- **TLS (STARTTLS)** is recommended in most cases
- Some providers require SSL instead

Always follow your email provider’s recommendations.

---

### Saving configuration

Click **Save** to store the SMTP configuration.

> 💡 After saving, it is recommended to send a test email before enabling tasks.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧪 Test mode

Several sections include a **“Use for test”** toggle.

When enabled:
- emails are sent only to the test recipient
- real users are not contacted

This is useful for:
- validating templates
- checking SMTP configuration
- previewing content safely

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📣 Campaigns

The **Campaigns** tab allows you to create **custom email campaigns**.

### Campaign editor

Fields:
- **Target server**  
  - all servers  
  - or a specific server
- **Subject**
- **Content**

Available variables:
- `{username}`
- `{email}`
- `{expiration_date}`

These variables are replaced automatically when emails are sent.

---

### Creating a campaign

1. Fill in the subject and content
2. Select target server(s)
3. (Optional) enable test mode
4. Click **Create campaign**

Campaigns are processed by automated tasks.

> ⚠️ Campaigns are not sent instantly unless the mailing task runs.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📝 Email templates

The **Templates** tab defines **automatic notification emails**.

These templates are used by background tasks.

---

### 📩 Expired subscription template

Sent when:
- a user’s subscription has expired
- access is suspended

Typical content:
- expiration date
- explanation of access suspension
- renewal information

---

### ⏳ Pre-expiration warning template

Sent **X days before expiration**, configurable per template.

Used to:
- warn users early
- reduce unexpected access loss

---

### 🔔 Reminder template

Sent closer to expiration (e.g. 7 days before).

Acts as a final reminder.

---

### Template fields

Each template includes:
- **Subject**
- **Content**
- **Days before expiration**
- **Test mode toggle**

---

### Available variables

Templates support:
- `{username}`
- `{email}`
- `{expiration_date}`
- `{days_left}`

> 💡 Variables are replaced dynamically when emails are sent.

---

### Saving templates

Click **Save templates** to apply changes.

You can also send a **test email** to preview the result.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🔄 How mailing works internally

<span style="display:inline-block;padding:10px 12px;border-radius:12px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;">
<b>Important concept</b><br>
Mailing does not send emails immediately.<br>
Emails are sent by scheduled tasks.
</span>

Flow:
1. Subscriptions define expiration dates
2. Templates define what should be sent
3. Mailing tasks detect eligible users
4. Emails are sent via SMTP

If mailing tasks are disabled, **no email will be sent**, even if everything is configured.

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 🧯 Troubleshooting

### Emails are not sent
- verify mailing is enabled
- check SMTP configuration
- ensure mailing tasks are enabled
- inspect **Logs**

---

### SMTP errors
- verify credentials
- verify TLS/SSL settings
- check port and host

---

### Users do not receive reminders
- verify email addresses are available
- check template delays
- ensure reminder tasks are active

<hr style="border:0;border-top:1px solid #1f2a44;margin:18px 0;" />

## 📌 Notes

- Mailing depends entirely on tasks and scheduler execution.
- Test mode should be used before enabling real emails.
- Avoid editing templates without testing.

<br>

<div align="center">
<span style="display:inline-block;padding:6px 10px;border-radius:999px;background:#0b1220;border:1px solid #1f2a44;color:#9fb2d8;font-size:12px;">
VODUM • Mailing documentation
</span>
</div>
