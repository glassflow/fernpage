"""The pages a new Fernpage starts with, so the first screen isn't empty."""

from app.store import Store

WELCOME = """Fernpage keeps your team's notes in one place.

## What you can do

- Make a page with **+ New page**, or a sub-page with the **+** next to any page.
- Write in markdown. **Bold**, *italics*, `code`, lists and [links](https://example.com) all work.
- Star a page to pin it under **Favourites**.
- Search every page from the box at the top of the sidebar.

## Tasks

- [x] Open Fernpage
- [ ] Write your first page
- [ ] Invite a teammate
"""

HANDBOOK = """How we work at Ridgeline Studio.

## Core hours

10:00 to 16:00 in your own timezone. Outside those hours, nobody expects a reply.

## Where things live

- Product specs: under **Product**
- Meeting notes: under **Meetings**, one page per meeting
- Decisions: written at the bottom of the meeting page they were made in
"""

ROADMAP = """## Now

- Comments on pages
- Share a page with a public link

## Next

- Page templates
- Trash, with restore

## Later

- Mentions and notifications
- Offline mode
"""

STANDUP = """**Attendees:** Priya, Marco, Lena, Sam

## Updates

- Priya: comments design is ready for review
- Marco: search is slow past a few thousand pages, looking into an index
- Lena: onboarding checklist copy done

## Decisions

- Public links are read-only in the first version.
"""


def seed(store: Store) -> None:
    welcome = store.create("Getting started", WELCOME, "🌱")
    store.update(welcome["id"], favorite=True)
    handbook = store.create("Team handbook", HANDBOOK, "📘")
    checklist = "- [ ] Laptop\n- [ ] Accounts\n- [ ] First pairing session\n"
    store.create("Onboarding checklist", checklist, "✅", handbook["id"])
    product = store.create("Product", "Everything about what we build next.", "🧭")
    roadmap = store.create("Roadmap", ROADMAP, "🗺️", product["id"])
    store.update(roadmap["id"], favorite=True)
    meetings = store.create("Meetings", "One page per meeting.", "🗓️")
    store.create("Standup, Monday", STANDUP, "☕", meetings["id"])
