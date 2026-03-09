# VODUM – Development TODO

This document lists the planned improvements, bug fixes, and future features for VODUM.

---

# 1. Plex User Creation Issues

- [/] **Plex invitation email is not sent**
  - When creating a Plex user, the invitation email is not sent.
  - The user therefore does not receive the Plex invitation link.

---

# 2. Multi-Admin System

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

# 3. User Portal (User UI)

Introduce a **separate interface for end users**.

Terminology:

- **Admin UI** → current interface
- **User UI** → new interface for end users

---

## 3.1 Domain Configuration

- [ ] Add a **domain configuration setting**
- Configured in **Admin UI → Settings**
- Displayed in **User UI → General page**

---

## 3.2 User Profile Access

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

## 3.3 Server & Library Access

Users should be able to see:

- [ ] which **servers** they have access to
- [ ] which **libraries** they can access

---

## 3.4 User Monitoring Dashboard

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

## 3.5 WWIW Integration

Evaluate integration of **WWIW (What Will I Watch)** into the User UI.

Possible features:

- personalized recommendations
- browsing suggestions

---

## 3.6 User Authentication & Password Management

- [ ] Add password management for users
- Users should be able to **change their password**

Requirements:

- At least **one notification system must be configured**
  (email or other) for password recovery.

---

## 3.7 Plex Authentication

Investigate **login via Plex account**.

Considerations:

- Users may belong to **multiple Plex servers**
- Authentication should rely on the **Plex user account**, not the server.

Verify compatibility with:

- multi-server setups
- current VODUM user linking logic

---

# 4. Monitoring follow-up

- [X] **Audit all monitoring queries for date-window consistency**
  - Ensure all historical period filters use `stopped_at`
  - Avoid mixed logic between `started_at` and `stopped_at` across tabs

- [X] **Audit all monitoring aggregations for session dedup consistency**
  - Ensure all `play_key` constructions use the same logic
  - Avoid per-day dedup where per-play/per-minute dedup is expected

- [X] **Audit all monitoring tabs for media type consistency**
  - Ensure series detection uses reliable fields such as `grandparent_title`
  - Avoid inconsistent `media_type` normalization between Overview / Activity / Servers / Users

- [X] **Review remaining monitoring queries after recent fixes**
  - Verify Overview
  - Verify Activity
  - Verify Users
  - Verify Servers
  - Verify History
  - Verify Libraries

- [X] **Validate 7d / 1m / 6m / 12m ranges everywhere**
  - Confirm all ranges are truly gliding windows
  - Confirm displayed stats match real historical totals

---

# Future Ideas

- Improve **cross-tool integration**
- Enhance **analytics for user activity**
- Expand **recommendation systems**