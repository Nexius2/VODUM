# Communications

Communications sends emails and Discord messages to your users: automatic
notifications (expiration, welcome, reminders…), campaigns you write yourself,
and replies to messages sent from the portal.

## Quick start

1. Configure the channels: SMTP for email and/or Discord. Send a test.
2. Review the templates of the automatic notifications you want to use.
3. To write to many users at once, create a campaign, send a test, then click send.
4. Follow what was sent in the delivery history.

## Channels

Fill in the SMTP host, port, sender, TLS and login, and configure Discord if
needed. Passwords and tokens are hidden when you edit the form; leaving the field
empty keeps the saved value. Always send a test before turning on scheduled messages.

When Discord is disabled, the choices that use Discord disappear for new messages.
A choice already saved stays as it is until you change it.

## Templates

A template is used for an event, a server type, a plan and a timing. Events
include expiration, user creation, pending-invitation reminders, referral
rewards, expiration date changes, blocked streams and plan-upgrade suggestions.
Use the **variables** dialog of the editor to insert the placeholders. Attachments
are stored with the template.

## Campaigns

A campaign targets users by server, server type and plan, can include attachments,
and can be tested first. **Saving does not send**: check the recipients and the
content, then use the send button.

By default a new campaign targets **All active users** (statuses *Active*,
*Reminder* and *Expiring soon*). Choose **All users** to include every status.
Only users with a linked media account receive it.

## Inbox

When quick messages are enabled in the [portal settings](user-portal.md#support),
users can write to you from their support page. Reply in **Communications → Inbox**.
Each user only sees their own conversation.

## Delivery and history

Scheduled messages are sent in order, following the channel order you set, with
a few automatic retries. The history shows the channel, status and recipient.
A message that is saved, queued or tested is not proof that it was received.

If a message stays pending, check [Tasks](tasks.md) and [Logs](logs.md).
