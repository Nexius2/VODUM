# VODUM – Development TODO

This document lists the planned improvements, bug fixes, and future features for VODUM.

---

# 1. Tasks / Automation Issues

- [ ] **`import_tautulli` task runs unexpectedly**
  - The `import_tautulli` task appears to run periodically even when no schedule is configured.
  - Investigate why the task is triggered automatically.
  - Ensure the task runs **only when explicitly scheduled**.

---

# 2. Plex User Creation Issues

- [ ] **Plex invitation email is not sent**
  - When creating a Plex user, the invitation email is not sent.
  - The user therefore does not receive the Plex invitation link.

- [ ] **Duplicate user state in Plex**
  - Users remain in the **Invites** section.
  - The same user may also appear in the **Users** list.

- [ ] **Library permissions not applied on user creation**
  - When creating a user, the assigned libraries are not correctly applied.
  - Verify the access grant process.

- [ ] **Email sending fails if SMTP is not configured**
  - When SMTP is not configured, the process fails.
  - Expected behavior:
    - either skip email sending gracefully
    - or show a clear error message in logs/UI.

---

# 3. UI Consistency

## User Detail Page

- [ ] **Date formatting inconsistency**
  - Creation date and expiration date are not displayed consistently.
  - Verify formatting for:
    - creation date
    - expiration date
    - renewal date

---

# 4. Monitoring Improvements

## Monitoring Overview

- [ ] **Add server tooltip statistics**
  - Display a tooltip showing:
    - number of **active sessions**
    - number of **transcoding sessions**
  - Data should be displayed **per server**.

---

# 5. Plex User Profile Integration

- [ ] **Link to open user directly in Plex**
  - Add a button in the user profile that opens the user in Plex.

### Considerations

A user may exist on **multiple Plex servers**.

Possible solutions:
- allow selecting which server to open
- or open **multiple Plex server pages**

---

# 6. Multi-Admin System

Support multiple administrator accounts.

## Admin Account Management

Add a new section:

**Settings → Accounts**

Features:

- [ ] Create admin account
- [ ] Edit admin account
- [ ] Remove admin account

Admin accounts should have:

- Full access to the **Admin UI**

---

# 7. User Portal (User UI)

Introduce a **separate interface for end users**.

Terminology:

- **Admin UI** → current interface
- **User UI** → new interface for end users

---

## 7.1 Domain Configuration

- [ ] Add a **domain configuration setting**
- Configured in **Admin UI → Settings**
- Displayed in **User UI → General page**

---

## 7.2 User Profile Access

Users should be able to view their account information.

Changes required:

- [ ] Rename `notes` → `admin_notes`
- [ ] Add new field `user_notes`

Users can edit only the following fields:

- firstname
- lastname
- secondary_email
- discord_user_id
- discord_username
- notification_system_order

Editing should only be allowed if enabled in **Admin UI settings**.

---

## 7.3 Server & Library Access

Users should be able to see:

- [ ] which **servers** they have access to
- [ ] which **libraries** they can access

---

## 7.4 User Monitoring Dashboard

Add a **monitoring page dedicated to the user** showing only their own activity.

### Usage Statistics

Display:

- total watch time
- total sessions

Time ranges:

- last 24 hours
- last 7 days
- last 30 days

### Media Type Distribution

- [ ] Donut chart showing media types (movies, series, etc.)

### Session Activity

- [ ] Graph displaying sessions over time:
  - per day
  - last 7 days
  - last 30 days
  - last year
  - all time

### Device / Player Statistics

- [ ] Top players / devices used

### Viewing History

- [ ] Full playback history

---

## 7.5 WWIW Integration

Evaluate integration of **WWIW (What Will I Watch)** into the User UI.

Possible features:

- personalized recommendations
- browsing suggestions

---

## 7.6 User Authentication & Password Management

- [ ] Add password management for users
- Users should be able to **change their password**

Requirements:

- At least **one notification system must be configured**  
  (email or other) for password recovery.

---

## 7.7 Plex Authentication

Investigate **login via Plex account**.

Considerations:

- Users may belong to **multiple Plex servers**
- Authentication should rely on the **Plex user account**, not the server.

Verify compatibility with:

- multi-server setups
- current VODUM user linking logic

---

# Future Ideas

- Improve **cross-tool integration**
- Enhance **analytics for user activity**
- Expand **recommendation systems**