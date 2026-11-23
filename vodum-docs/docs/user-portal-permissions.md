# Portal permissions

The portal is disabled until configured. Hiding a link is never an authorization
check: the server validates session, account state, feature visibility, named
permission and ownership as applicable to the request.

| Resource | Administrator | Portal user |
| --- | --- | --- |
| Administration and global APIs | Administration access | No access |
| Profile | Manage permitted user records | Own profile, allowlisted fields only |
| Subscription | Manage plans and dates | Own subscription and enabled renewal information |
| Accounts and library access | Manage provider accounts/grants | Own access; supported profile edits only |
| Media requests | Configure services, defaults and routes | Submit through own eligible routes |
| Invitations | Configure and review referrals | Invite only when enabled and eligible |
| Monitoring | Global sessions, reports and map | Own permitted playback summaries |
| Support | Configure and handle Inbox | Own conversation and configured contact details |
| Portal API | Administrative permissions do not replace a user-owned API context | Own session-scoped response |
| Notes, technical logs and secrets | According to the administrative workflow | Never exposed |

Portal reads must not accept a browser-supplied `vodum_user_id` as authority.
Provider subjects are linked by validated identity and ownership, not by display
name alone. An identity already attached to another account cannot simply be
reassigned by a user.

Revocable server-side sessions are checked against current state. API responses
exclude secrets, provider URLs/raw payloads, full IP addresses and other users'
records, and use `Cache-Control: no-store`. See [Security](security.md).
