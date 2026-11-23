# Subscriptions & gifts

Subscription templates define a plan name, duration, stream allowance and other
defaults. Templates can be enabled/disabled, duplicated, restored and assigned
to individual users or users from a server. Review the current user snapshot
and any override before assuming a later template edit changes every user.

The bundled **base sub**, **Family sub**, **Plus sub** and **Lifetime sub** plans
have no subscription amount filled in. An empty amount remains empty when
editing or duplicating a plan; an explicitly entered zero is still preserved.
Initial setup and **Restore default templates** use the same catalog.

**Lifetime sub** uses the lifetime option (no expiration), starts disabled and
hidden from the member portal, and has no preset stream policies. Review its
limits and enable it before assigning it. It is a bundled example, not the
automatically assigned default plan.

Existing plan values, customizations and user assignments are not overwritten
on upgrade. On an existing installation, use **Restore default templates** to
add the missing lifetime example. Restore inserts only missing plan names; it
does not clear amounts on plans that already exist. Deleted examples do not
reappear automatically at startup.

## Start and expiration

Expiration can start immediately or on first playback. First-playback activation
avoids consuming subscription time while an invitation is still unused.

| Mode | Effect |
| --- | --- |
| None | Track status without automatic access enforcement |
| Warn only | Notify and apply the system expiration stream policy while keeping library shares |
| Warn then disable | Warn during the configured grace period, then remove access |
| Disable | Queue access removal when expiration is reached |

Renewal removes the system expiration policy and queues supported provider access
synchronization. Protected Plex owners and Jellyfin administrators are excluded
from normal subscription editing. Review queued work after bulk assignments.

## Gifts

Subscription gifts grant configured days to a selected user, users from a server
or the eligible global selection. Review the target scope, duration and history
before submitting a gift; it changes subscription dates rather than recording
an external payment.

History refreshes every 30 seconds while the page is in the foreground, resumes
when returning to it and refreshes after submission. A slow history read times
out in the browser after 10 seconds. An unchanged response or a temporary failure
keeps the last displayed history instead of replacing it with an empty list.

## Portal renewal information

The portal displays the user's current plan, dates and effective limits, plus
available plan/renewal information allowed by configuration. On mobile, the main
renewal action opens the configured information near the bottom of the screen.

Configured HTTPS renewal links can send users to an external destination.
Experimental payment-link settings are exposed in debug mode when enabled and
can describe PayPal.Me, Wero, bank transfer or custom instructions, with plan
scope and references. Displaying a link or copying payment details is not itself
proof of payment and does not promise an automatic renewal. Verify the enabled
workflow and actual payment before changing expiration.

For rewards and invited friends, see [Referrals & invitations](referrals.md).
