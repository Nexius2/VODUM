# Communications

Communications unifies email and Discord delivery.

## Configuration

Configure SMTP, sender address, TLS, Discord bot token, global channel mode and
delivery order. Password/token fields are intentionally blank while editing;
leaving them blank preserves the encrypted stored value. Test each channel
before enabling scheduled delivery.

## Templates

Templates are selected by event, provider, subscription scope and timing.
Events include expiration, user creation, pending-invite reminders, referral
rewards, expiration changes, blocked streams and usage-risk suggestions.

Use the variables dialog in the editor rather than guessing placeholders.
Attachments are stored on persistent storage and linked to the template.

## Campaigns

Campaigns target a server/provider/subscription scope, support test mode and may
include attachments. Saving a campaign does not send it; use the explicit send
action after reviewing recipients and content.

## Delivery and history

Scheduled messages enter one unified queue. The worker applies channel fallback,
bounded retries and catch-up for final scheduled email failures. History records
channel, status, recipient context, content and error details. Cooldowns for
usage-risk suggestions begin only after successful delivery.
