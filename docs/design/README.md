# Design reference

The two files here are the mockups the user reviewed and approved before the GUI was restyled (ADR 10). They are static HTML with flat placeholder blocks where footage would be, so they contain no clips and can live in the repository.

| File                       | What it shows                                                                                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `review-dark.mockup.html`  | The approved Review screen at 1440x900 in the dark set: icon rail, top bar, card anatomy, montage strip, right panel. This is the reference the code follows. |
| `review-light.mockup.html` | A lighter, editorial sketch of the same screen. It fixes the light palette, not the layout: the layout is the dark file's.                                    |

Open them in a browser to read them. They pull Space Grotesk and IBM Plex Mono from Google Fonts, so they need a network connection to look right; the application ships the same two families as package data instead.

The values in them are not the source of truth for the code. `autocut/gui/theme/tokens.py` is, and it was written from these files. When a colour or a size has to change, change the tokens and leave the mockups as the record of what was approved.
