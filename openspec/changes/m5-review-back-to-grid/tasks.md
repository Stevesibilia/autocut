## 1. Exit from the montage

- [ ] 1.1 Add `Back to clips` to the montage transport, an Escape shortcut scoped to the montage widget, and make the top bar action toggle between `Play all` and `Back to clips`; all three call `show_grid`, which also selects the clip that was playing. Tests press the button and the shortcut and assert the grid is current, the last clip is selected and the action label reads Play all.
- [ ] 1.2 Gates: `make lint`, `dev-gui` gui suite. Update CHANGELOG.
