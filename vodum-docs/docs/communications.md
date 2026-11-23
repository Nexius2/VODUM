# Communications

Communications groups configuration, templates, campaigns, delivery history and
portal conversations for email and Discord.

## Configure channels

Set SMTP host/port, sender, TLS and authentication, and configure Discord when
needed. Secret fields are blank/masked when editing; leaving them blank preserves
the encrypted stored value. Test delivery before enabling scheduled messages.

Channel selectors offer choices compatible with the configured services.
Disabling Discord removes Discord-only and combined choices from new selections.
An existing saved choice that becomes unavailable remains preserved until it is
explicitly replaced. Global/inherited choices describe the currently configured
channels; the Discord message counter appears when Discord is part of the selection.

## Templates

Templates are selected by event, provider, subscription scope and timing.
Events include expiration, user creation, pending-invite reminders, referral
rewards, expiration changes, blocked streams and usage-risk suggestions.
Use the editor's variables dialog rather than guessing placeholder names.
Attachments are stored on persistent storage and linked to the template.

## Campaigns

Campaigns target the supported server/provider/subscription scope, offer test
sending and may include attachments. Saving is not sending: review recipients
and content, then use the explicit send action. Manual campaign email footers
show the application name; template notifications retain the automated-message
notice where applicable.

New campaigns default to **All active users**, including **Active**, **Reminder**
and **Expiring soon** statuses. Choose **All users** to include other statuses.
Only users with a linked media account are eligible. Server, provider and
subscription filters apply together with this audience choice when recipients
are queued. Existing campaigns keep their previous all-users scope until edited;
already queued recipients are unchanged.

## Inbox and portal support

When portal quick messages are enabled, users can write in their personal support
page. Administrators handle those conversations in **Communications → Inbox**.
Message history is scoped to the conversation; users cannot read another person's
thread. Support contact visibility and quick messages are independently configured
in [portal settings](user-portal.md#support).

## Delivery and history

Scheduled messages enter the unified delivery queue. The worker applies configured
channel ordering/fallback, bounded retries and supported catch-up for final
scheduled email failures. History records channel, status and recipient/content
context. A saved item, queued delivery or test request is not a confirmed receipt.

Usage-risk recommendation history is refreshed by a scheduled task; sending
rechecks eligibility and cooldown. A suggestion cooldown starts after successful
delivery, rather than merely opening a report. See [Tasks](tasks.md) and [Logs](logs.md)
when a message stays pending.
