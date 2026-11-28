# Referrals & invitations

Three different things are called "invitation" in VODUM. This page explains
each of them.

| Invitation | What it is for | Where to check the result |
| --- | --- | --- |
| Portal activation | The user activates their own [portal](user-portal.md) account | Activation link and account state |
| Plex/Jellyfin invitation | Gives the user access to your media server | Accepted invitation and library access on the user page |
| Referral invitation | An existing user invites a friend, who may earn them a reward | **Users → Referrals** |

## Quick start: referrals

1. Open **Users → Referrals**, then **Referral settings**.
2. Turn referrals and rewards on, set the qualification and reward periods, and
   which statuses can take part.
3. If you want users to invite friends themselves, enable invitations in the
   portal settings.
4. Follow referrals in **Users → Referrals**.

## Follow referrals

The list shows who invited whom, the qualification date, the status and the
reward days. Filter it, show active, archived or all referrals, and archive or
restore several at once. A pending referral has not earned its reward yet: check
its state before changing a subscription by hand.

## Invitations from the portal

When enabled, an active user can invite a friend from their subscription page.
The friend gets the same plan and the same servers as the person who invited
them; the user cannot choose other servers or rights. VODUM checks the email,
refuses an address that already exists, records the referral and sends the
invitations.

If part of it fails (email, or invitation on a server), VODUM reports a partial
success: check the new user's page.

!!! note "Good to know"
    A sent email does not mean the media-server invitation was accepted, and a
    qualified referral does not mean a payment was received.

See also [Subscriptions](subscriptions.md) and [Communications](communications.md).
