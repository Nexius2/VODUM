# Target library choices

Creation and duplication offer only compatible movie/series libraries on media servers whose saved status is `up`. Offline and unknown-status servers are excluded. This uses the status already maintained by the server-health task, without live pings while opening the wizard.

Editing retains every originally attached primary/secondary library even if its server is down or unknown. Those options are labelled Server offline. Other offline libraries remain unavailable as new targets. The full library metadata stays in the page data so saved collection rows and history remain readable. Existing chart/type restrictions still apply.

The exception is reset when opening a new creation or duplication wizard, preventing offline attachments from leaking into new-target choices. Availability reflects the saved server state when the page was loaded; reload after a server-health update to refresh the choices.
