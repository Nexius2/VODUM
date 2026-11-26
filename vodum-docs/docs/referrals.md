# Referrals & invitations

Referral rewards, portal account invitations and invitations to a media server
are related workflows, but they do not mean the same thing.

## Referral administration

Open **Users → Referrals** to review referrer/referred pairs, qualification dates,
status and reward-day snapshots. Filter the list and switch between active,
archived or all records. Bulk archive/restore acts on the selected records.

In **Referral settings**, configure whether the feature and rewards are enabled,
qualification/reward periods, eligible statuses, automatic expiry/archive behavior
and supported notifications. A pending referral is not an earned reward. Inspect
the qualification and reward state before adjusting a subscription manually.

## User invitations from the portal

When enabled in portal settings and the subscription section is available,
an active user can invite a friend from their subscription page. The server
builds the invitation from the inviter's current subscription snapshot and
eligible linked provider access. Browser fields cannot select arbitrary servers,
privileges or a different referrer.

The workflow validates the email, prevents an already-known address from creating
a duplicate account, records the referral relationship and attempts provider
provisioning/delivery. Protected or unusable provider identities are not copied
as arbitrary administrator access. A partial provider or email failure is reported
as partial success and requires administrator review.

## Distinguish the invitation states

| Invitation | Purpose | What to verify |
| --- | --- | --- |
| Portal activation | Activate a user's own portal account | Activation link, account state and recovery settings |
| Plex/Jellyfin provisioning | Establish media-server access | Provider result, accepted invitation and library grants |
| Referral invitation | Create a referred user from allowed inviter settings | Qualification/reward state and provisioning result |

A sent email is not proof that a media-server invitation was accepted, and a
qualified referral is not proof that an unrelated payment was received.
See [Subscriptions](subscriptions.md), [Communications](communications.md) and
[User portal](user-portal.md) for the remaining steps.
