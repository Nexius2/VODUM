# Portal permissions

What a portal user can see and do, compared with you as administrator. Every
page is checked on the server: hiding a link is never the only protection.

| Resource | Administrator | Portal user |
| --- | --- | --- |
| Administration | Full access | No access |
| Profile | Edit users | Own profile, only the fields you allow |
| Subscription | Manage plans and dates | Own subscription and renewal information |
| Media accounts and libraries | Manage accounts and access | See own access; allowed profile changes only |
| Media requests | Configure services and routes | Request through own routed libraries |
| Invitations | Configure and review referrals | Invite a friend when enabled |
| Monitoring | All sessions, reports and map | Own playback summary |
| Support | Configure and answer in Inbox | Own conversation and your contact details |
| Notes, logs and secrets | Administration only | Never shown |

A user cannot see another user's data by changing an address or a form field.
A media account already linked to someone else cannot be taken over, and a
matching display name is not enough to link an account.

Portal sessions can be revoked and are checked on every request. See
[Security](security.md) and the [Portal API](portal-api.md).
