# Vodum — User Migration System

# Overview

The goal is to allow administrators to migrate users between media servers directly from Vodum.

Supported migration types:

* Plex → Jellyfin
* Plex → Plex
* Jellyfin → Jellyfin

The migration system should be designed as a controlled migration workflow/campaign and NOT as a blind user copy tool.

The administrator must always be able to:

* preview impacted users
* select destination libraries
* configure passwords
* configure communication
* execute progressively
* retry safely
* monitor migration progress

---

# Core Philosophy

Vodum already contains most required systems:

* Plex invitations
* Jellyfin user creation
* library management
* subscriptions
* communication templates
* task system
* background workers
* users/server relationships

The migration system should therefore be implemented as a new orchestration layer on top of existing provider systems.

Avoid duplicating:

* invite logic
* Jellyfin user creation
* communication sending
* library assignment
* task execution

---

# Supported Migration Types

# 1. Plex → Jellyfin

This is the most important migration scenario.

## What Vodum can do

* create Jellyfin users
* generate/set passwords
* assign Jellyfin libraries
* send credentials
* track migration status
* retry failed users
* progressive migration
* background execution

## What cannot be migrated

* Plex passwords
* watch history
* watchlists
* Plex authentication
* avatars
* managed user structures

This must be clearly explained in the UI.

---

# 2. Plex → Plex

There are TWO possible scenarios.

## Case A — Same Plex owner account

Example:

* MovieEmpire
* SerieEmpire

Both use the same Plex owner account.

In this situation:

* users already exist on destination server
* invitations are NOT required
* only library sharing is required

Vodum should detect this automatically.

## Detection logic

Compare:

* owner email
  OR
* Plex account ID
  OR
* machine/account identifier

If same owner:

Migration mode becomes:

# Direct Share Mode

Workflow:

* share destination libraries
* optional communication
* optional cleanup on source server

UI message example:

"Shared Plex ecosystem detected"

"Users already exist on destination Plex account"

This is the ideal Plex → Plex scenario.

---

## Case B — Independent Plex servers

If owners differ:

* users do not exist
* invitations are required

Migration workflow:

* send Plex invitations
* apply library sharing
* wait for acceptance
* optional communication templates

This is slower and depends on user acceptance.

UI message example:

"Independent Plex servers detected"

"Plex invitations required"

---

# 3. Jellyfin → Jellyfin

Very powerful scenario.

Unlike Plex:

* usernames can be preserved
* passwords can be preserved
* libraries can be replicated
* policies can be replicated

This allows almost transparent migration.

Potentially:

* same username
* same password
* same access
* minimal user impact

---

# Password Management

# Plex

Plex passwords CANNOT be migrated.

Vodum never has access to Plex account passwords.

---

# Jellyfin

Vodum can fully manage passwords.

Recommended options:

## Option A — Generate random passwords

Recommended default.

* secure
* auto-generated
* optionally emailed

---

## Option B — Admin-defined default password

Examples:

* Welcome123
* TempPassword2026

Optional checkbox:

* "Require user to change password manually"

---

## Option C — Preserve existing password

Only possible for:

* Jellyfin → Jellyfin

This creates the smoothest migration experience.

---

# Force password change on first login

Jellyfin probably does NOT support a true:

* "force password change on next login"

behavior like Active Directory or Keycloak.

Recommended behavior:

* preserve password
  OR
* generate temporary password

Then communicate:

"Please change your password after first login."

---

# Security Recommendations

# NEVER store passwords in plain text

If password re-display is needed:

* encrypt passwords
* do NOT hash only
* use Fernet encryption
* derive encryption key from SECRET_KEY

Otherwise:

* passwords cannot be resent later

---

# Recommended Database Additions

# jellyfin_credentials

```sql
CREATE TABLE jellyfin_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vodum_user_id INTEGER NOT NULL,
    server_id INTEGER NOT NULL,
    username TEXT,
    encrypted_password TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

# migration_campaigns

```sql
CREATE TABLE migration_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    source_server_id INTEGER,
    destination_server_id INTEGER,
    migration_type TEXT,
    status TEXT,
    options_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

# migration_users

```sql
CREATE TABLE migration_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    vodum_user_id INTEGER,
    status TEXT,
    details_json TEXT,
    started_at TEXT,
    completed_at TEXT
);
```

---

# Recommended Statuses

# Campaign statuses

* draft
* queued
* running
* paused
* waiting_users
* completed
* failed
* cancelled

---

# User migration statuses

* pending
* processing
* invited
* created
* waiting_acceptance
* completed
* failed

---

# UI Recommendations

# New sidebar section

Add:

* Migration

Suggested placement:

* Dashboard
* Monitoring
* Users
* Servers & Libraries
* Subscriptions
* Tasks
* Communications
* Migration
* Backup & Import
* Settings
* Logs

Migration deserves its own section because it is:

* advanced
* sensitive
* long-running
* potentially destructive

---

# Migration Dashboard

# Top cards

## Migration Overview

* active migrations
* completed migrations
* failed migrations
* waiting users

---

## Quick Actions

* New migration
* Retry failed
* Export report

---

# Migration Campaign Table

Columns:

* Name
* Source server
* Destination server
* Type
* Users
* Progress
* Status
* Created date
* Actions

---

# Migration Wizard

# Step 1 — Select migration type

Cards:

* Plex → Jellyfin
* Plex → Plex
* Jellyfin → Jellyfin

---

# Step 2 — Select servers

Dropdowns:

* source server
* destination server

Validation:

* source ≠ destination
* provider compatibility
* destination online
* token/API valid

---

# Step 3 — User selection

Large table:

* checkbox
* username
* email
* subscription
* expiration
* source libraries
* migration status

Filters:

* active only
* expired
* invited
* subscription
* search

---

# Step 4 — Migration mode

## Plex → Plex

Auto-detection:

### Shared owner detected

* Direct Share Mode available

OR

### Independent Plex servers detected

* Invitations required

---

# Step 5 — Password strategy

Only for Jellyfin migrations.

Options:

* generate random passwords
* admin-defined password
* preserve existing passwords
* no password handling

---

# Step 6 — Communication strategy

Reuse existing Communications system.

DO NOT hardcode emails/messages.

Use migration-specific templates.

---

# Suggested Communication Templates

## migration_jellyfin_created

Contains:

* server URL
* username
* password
* support contact
* login instructions

---

## migration_plex_invite_sent

Contains:

* Plex invitation explanation
* accept invite instructions
* migration date
* server information

---

## migration_completed

Optional final confirmation.

---

# Step 7 — Execution mode

Options:

## Immediate

Run now.

---

## Scheduled

Run at chosen date/time.

---

## Progressive batches

Examples:

* 10 users/hour
* 50 users/day

Very useful for large communities.

---

# Backend Architecture

# NEVER execute migrations inside Flask requests

Everything should run in background tasks.

Recommended new task:

* migration_worker

Responsibilities:

* process queue
* retry failures
* update progress
* write logs
* maintain idempotency

---

# Idempotency Requirements

Migration MUST be safely replayable.

Examples:

## Jellyfin user already exists

DO NOT fail.

Instead:

* reuse account
* optionally reset password
* optionally update libraries

---

## Plex invite already exists

DO NOT resend endlessly.

Track invitation state.

---

# Logs & Reporting

Migration requires detailed logging.

Examples:

* user created
* invite sent
* password generated
* email sent
* destination offline
* libraries applied
* migration completed

Logs should appear:

* migration page
* task logs
* global logs

---

# User Page Improvements

If user linked to Jellyfin:

Add:

# Jellyfin Credentials Section

Actions:

* show username
* reset password
* generate password
* send credentials
* force manual password update
* copy credentials

---

# Security UX

Passwords should NEVER be permanently visible.

Recommended behavior:

* hidden by default
* reveal button
* audit log when revealed

---

# Recommended Development Phases

# Phase 1

Implement:

* Plex → Jellyfin
* Jellyfin password handling
* migration campaigns
* communication integration

This already delivers massive value.

---

# Phase 2

Add:

* Plex → Plex
* owner detection
* direct share mode
* invitation tracking

---

# Phase 3

Add:

* Jellyfin → Jellyfin
* password preservation
* rollback tools
* scheduling
* advanced reports

---

# Strategic Value

This feature could become one of Vodum’s strongest differentiators.

Especially because:

* Plex pricing is evolving
* many admins are testing Jellyfin
* hybrid infrastructures are growing

Vodum could become:

# "The migration bridge between Plex and Jellyfin"

Very few tools currently handle this properly.
