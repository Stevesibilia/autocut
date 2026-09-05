# 10. Bundled GUI design system on the Fusion style

Date: 2026-09-05

## Status

Accepted

## Context

The desktop application built in M5 (ADR 9) took its appearance from the platform: the Fusion style reading the desktop palette on Linux, and the native style on macOS, on the reasoning that a Mac application should look like one. The result on both platforms is a stock Qt form, with a list widget for navigation, grey rectangles for thumbnails and a handful of inline stylesheet calls with literal colours. The user reviewed a design mockup of the Review screen and approved it: a dark surface, a slim icon rail, rounded cards with pill badges, one accent colour for the machine's choices and two for the user's decisions, a grotesque sans for text and a monospace face for every number.

Two forces pull against each other. A native look is free and familiar, but Qt's macOS style paints its own controls and ignores most of a stylesheet, so a design system cannot be layered on it; the same stylesheet would render two different applications on the two platforms this project supports. A consistent branded look requires the application to bring its own style, fonts and icons, which adds package data and departs from platform conventions. The application is single purpose and will be distributed as a bundle (ADR 7), so platform integration matters less than it would for a document editor.

Fonts are a specific case of the same tension. Neither platform ships a suitable grotesque or a monospace with tabular figures under a licence that allows bundling, and relying on installed fonts gives different metrics on every machine. Icons have the same problem in reverse: platform icon sets differ entirely between Linux desktops and macOS.

## Decision

We will apply the Fusion style on every platform, with a palette and a stylesheet generated from one token module in `autocut/gui/theme`, dark by default and light or system on request through `gui.theme`. We will bundle Space Grotesk and IBM Plex Mono under the SIL Open Font License and a subset of the Lucide icon set under the ISC licence as package data, register the fonts at startup and render the icons from SVG recoloured with the token colours. Every widget and painter reads colours and sizes from the tokens; no colour literal lives outside the theme package.

## Consequences

The application looks the same on Linux and macOS, screenshots from the Linux development machine describe what the Mac will show, and a visual change is a token change. The stylesheet and palette are tested once for both token sets, and the card, rail and timeline vocabulary is shared by every screen.

The application no longer looks native on macOS: no vibrancy, no system accent colour, no automatic response to a live theme switch until restart. The wheel grows by under a megabyte of fonts and icons, the PyInstaller specification must collect that directory, and a third party licence file joins the repository. Font rendering still differs slightly between FreeType and CoreText, so type sizes are chosen with that in mind and checked in screenshots on both platforms. This supersedes the part of the M5 shell design that left the macOS native style untouched; ADR 9 stands for everything else.
