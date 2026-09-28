"""Screen 4: the two pass music loop, prompt out and track in.

AutoCut cannot make the music, so this screen is built around the handover: it hands
over a prompt that is ready to paste, and takes back whatever came out of Suno, which
is never quite the tempo that was asked for. Both halves are on one screen because
they are one loop, and the user comes back to the left half when the right half says
the track drifted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from autocut.core.beatsync import (
    AudioUnavailableError,
    QuantizeResult,
    Track,
    compare_bpm,
    decode_audio,
    measure_track,
    quantize_durations,
    record_sync,
    reset_final_bounds,
    synced_against,
    write_beatmap,
)
from autocut.core.config import GenreRow
from autocut.core.events import ProgressCallback, ProgressEvent
from autocut.core.manifest import PromptVariant
from autocut.core.montage import MontageResult, discard
from autocut.core.providers import TextProvider, cloud_enabled, find_key
from autocut.core.soundtrack.build import (
    SoundtrackResult,
    build_soundtrack,
    store_user_variant,
    write_prompt_file,
)
from autocut.core.soundtrack.prompt import MoodDirection, RoomDirection, apply_mood
from autocut.gui import theme
from autocut.gui.state import ProjectState
from autocut.gui.widgets.montage import MontagePlayer, clip_labels
from autocut.gui.widgets.prompt_editor import PromptEditor
from autocut.gui.widgets.waveform import WaveformView, load_or_build_envelope

AUDIO_FILTER = "Audio (*.mp3 *.wav *.m4a *.flac *.ogg *.aac);;All files (*)"

MOOD_POSITIONS: tuple[MoodDirection, ...] = ("calmer", "keep", "energetic")
ROOM_POSITIONS: tuple[RoomDirection, ...] = ("intimate", "keep", "cinematic")


@dataclass(frozen=True)
class TrackLoad:
    """What the track stage measured, or why it could not.

    A file that will not decode is an answer, not a stage failure: the reason goes in
    the track label, where the user is looking, rather than into an error dialog.
    """

    path: Path
    track: Track | None = None
    pairs: np.ndarray | None = None
    error: str | None = None


def _scrolled(inner: QWidget) -> QScrollArea:
    """`inner` in a scroll area that never scrolls sideways, only down."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


class SoundtrackScreen(QWidget):
    """The prompt on the left, the track and the beat grid on the right."""

    prompt_written = Signal(str)
    synced = Signal()
    track_loaded = Signal(bool)
    """A track load ended: True with the track on screen, False with the reason shown."""

    def __init__(self, state: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("screen-soundtrack")
        self._state = state
        self._track: Track | None = None
        self._audio: Path | None = None
        self._preview: QuantizeResult | None = None
        # The variants as the template produced them, before any mood move. Every move
        # is applied to these rather than to the last result, so "as matched" really
        # goes back and asking for calmer twice is not calmer twice.
        self._generated: list[PromptVariant] = []
        # A genre or BPM change that arrived while a generation ran on the worker. Kept
        # as one flag rather than a queue: only the controls' last position matters.
        self._regenerate_pending = False

        # --- the prompt half -------------------------------------------------
        self.editor = PromptEditor(state.config, self)
        self.editor.changed.connect(self._prompt_edited)

        self.variant_box = QComboBox()
        self.variant_box.currentIndexChanged.connect(self._variant_chosen)
        self.genre_box = QComboBox()
        self.genre_box.currentIndexChanged.connect(self._regenerate_from_controls)
        self.bpm_field = QSpinBox()
        self.bpm_field.setRange(40, 220)
        self.bpm_field.setKeyboardTracking(False)
        self.bpm_field.editingFinished.connect(self._regenerate_from_controls)

        # Labelled by their ends rather than by a one word name: "Mood" and "Room" told
        # a reader neither which way the control goes nor what it does.
        self.mood_box = QComboBox()
        self.mood_box.addItems(["calmer", "as matched", "more energetic"])
        self.mood_box.setCurrentIndex(1)
        self.room_box = QComboBox()
        self.room_box.addItems(["intimate", "as matched", "cinematic"])
        self.room_box.setCurrentIndex(1)
        for box in (self.mood_box, self.room_box):
            box.currentIndexChanged.connect(self._mood_changed)

        self.matched_label = QLabel()
        self.matched_label.setWordWrap(True)
        self.refine_note = QLabel()
        self.refine_note.setWordWrap(True)
        self.refine_note.setProperty("role", "muted")

        self.generate_button = QPushButton("Generate the prompt")
        self.generate_button.clicked.connect(self.generate)
        self.save_edit_button = QPushButton("Keep my edit")
        self.save_edit_button.clicked.connect(self.store_edit)
        self.write_button = QPushButton("Write suno-prompt.md")
        self.write_button.clicked.connect(self.write_file)

        controls = QHBoxLayout()
        for label, widget in (
            ("Variant", self.variant_box),
            ("Genre", self.genre_box),
            ("BPM", self.bpm_field),
            ("Calm to energetic", self.mood_box),
            ("Intimate to cinematic", self.room_box),
        ):
            controls.addWidget(QLabel(label))
            controls.addWidget(widget)
        controls.addStretch(1)

        prompt_actions = QHBoxLayout()
        prompt_actions.addWidget(self.generate_button)
        prompt_actions.addWidget(self.save_edit_button)
        prompt_actions.addWidget(self.write_button)
        prompt_actions.addStretch(1)

        prompt_box = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_box)
        prompt_layout.setSpacing(theme.METRICS.space + 2)
        prompt_layout.addWidget(self.matched_label)
        prompt_layout.addLayout(controls)
        prompt_layout.addWidget(self.editor, 1)
        prompt_layout.addLayout(prompt_actions)
        prompt_layout.addWidget(self.refine_note)

        # --- the track half --------------------------------------------------
        self.waveform = WaveformView()
        self.track_label = QLabel("No track loaded")
        self.track_label.setProperty("role", "title")
        self.comparison_label = QLabel()
        self.comparison_label.setWordWrap(True)
        self.distribution_label = QLabel()
        self.distribution_label.setWordWrap(True)
        self.distribution_label.setTextFormat(Qt.TextFormat.PlainText)
        self.distribution_label.setProperty("role", "muted")
        self.distribution_label.setFont(theme.font(theme.METRICS.body_size, mono=True))

        self.load_button = QPushButton("Load a track…")
        self.load_button.setProperty("variant", "primary")
        self.load_button.clicked.connect(self._browse_track)
        self.override_field = QDoubleSpinBox()
        # Wider than the prompt's own field: a beat tracker reading double a slow track
        # gives a number no prompt would ever have asked for, and the override has to
        # be able to say it.
        self.override_field.setRange(0.0, 400.0)
        self.override_field.setDecimals(1)
        self.override_field.setSpecialValueText("measured")
        self.override_field.valueChanged.connect(self._override_changed)
        self.apply_button = QPushButton("Apply sync")
        self.apply_button.setProperty("variant", "quiet")
        self.apply_button.clicked.connect(self.apply_sync)
        self.apply_button.setEnabled(False)
        self.play_with_track_button = QPushButton("Play with track")
        self.play_with_track_button.clicked.connect(self.play_with_track)
        self.play_with_track_button.setEnabled(False)
        self.montage = MontagePlayer(self)
        self.montage.setVisible(False)

        bpm_label = QLabel("Use BPM")
        bpm_label.setProperty("role", "label")
        track_actions = QHBoxLayout()
        track_actions.addWidget(self.load_button)
        track_actions.addWidget(bpm_label)
        track_actions.addWidget(self.override_field)
        track_actions.addWidget(self.apply_button)
        track_actions.addWidget(self.play_with_track_button)
        track_actions.addStretch(1)

        track_box = QGroupBox("Track")
        track_layout = QVBoxLayout(track_box)
        track_layout.setSpacing(theme.METRICS.space + 2)
        track_layout.addWidget(self.track_label)
        track_layout.addWidget(self.waveform, 1)
        track_layout.addLayout(track_actions)
        track_layout.addWidget(self.comparison_label)
        track_layout.addWidget(self.distribution_label)
        track_layout.addWidget(self.montage, 1)

        # Each half in its own scroll area. The prompt column alone is taller than a
        # 680 px window, and a screen that cannot scroll is a screen with controls the
        # user cannot reach.
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_scrolled(prompt_box), 3)
        layout.addWidget(_scrolled(track_box), 2)

        state.project_changed.connect(self.reload)
        state.selection_changed.connect(self.refresh_preview)
        state.stage_started.connect(lambda _name: self._set_running(True))
        state.stage_finished.connect(self._stage_finished)
        state.stage_cancelled.connect(lambda _name: self._set_running(False))
        state.stage_ended.connect(self._stage_ended)
        # Also on error: a failed stage emits neither finished nor cancelled, and
        # without this the screen stayed disabled until the next stage ran.
        state.error.connect(lambda _message: self._set_running(False))

        self.reload()

    # --- filling in -------------------------------------------------------

    def reload(self) -> None:
        """Show whatever the project already has: a prompt, a track, or neither."""
        state = self._state
        manifest = state.manifest
        self.genre_box.blockSignals(True)
        self.genre_box.clear()
        self.genre_box.addItem("as matched", None)
        for row in state.config.soundtrack.genres:
            self.genre_box.addItem(row.name, row.name)
        self.genre_box.blockSignals(False)

        if manifest is None:
            self.matched_label.setText("Open a project and select some clips first.")
            self.editor.show_variant(None)
            self._generated = []
            self._set_variants([])
            return
        soundtrack = manifest.soundtrack
        self._generated = [item for item in soundtrack.variants if item.source != "user"]
        self.bpm_field.blockSignals(True)
        self.bpm_field.setValue(int(soundtrack.proposed_bpm or 120))
        self.bpm_field.blockSignals(False)
        self._describe_match()
        self._set_variants(soundtrack.variants)
        self._describe_refinement()
        if soundtrack.audio_path is not None and Path(soundtrack.audio_path).exists():
            self.load_track(Path(soundtrack.audio_path))
        else:
            self.waveform.clear()
            self.refresh_preview()

    def _describe_match(self) -> None:
        manifest = self._state.manifest
        if manifest is None:
            return
        soundtrack = manifest.soundtrack
        signals = soundtrack.signals
        if soundtrack.matched_row is None:
            selected = sum(1 for s in manifest.segments.values() if s.outcome == "selected")
            self.matched_label.setText(
                f"{selected} clips selected. Generate the prompt to match a genre."
            )
            return
        parts = [f"{soundtrack.genre} (row {soundtrack.matched_row}): {soundtrack.matched_reason}"]
        if signals is not None:
            parts.append(
                f"{signals.clip_count} clips, {signals.total_duration_s:.1f} s, "
                f"{signals.energy_band} energy, {signals.time_of_day}"
            )
        if soundtrack.beat_distance is not None:
            parts.append(f"mean distance from a whole beat {soundtrack.beat_distance:.3f}")
        self.matched_label.setText("  |  ".join(parts))

    def _set_variants(self, variants: list[PromptVariant]) -> None:
        self.variant_box.blockSignals(True)
        self.variant_box.clear()
        for index, variant in enumerate(variants, start=1):
            label = {"user": "yours", "refined": "refined"}.get(variant.source, "template")
            self.variant_box.addItem(f"{index} ({label})", index - 1)
        self.variant_box.blockSignals(False)
        manifest = self._state.manifest
        chosen = manifest.soundtrack.chosen_variant if manifest is not None else 0
        if variants:
            self.variant_box.setCurrentIndex(min(chosen, len(variants) - 1))
            self.editor.show_variant(variants[min(chosen, len(variants) - 1)])
        else:
            self.editor.show_variant(None)
        self.write_button.setEnabled(bool(variants))
        self.save_edit_button.setEnabled(bool(variants))

    def _describe_refinement(self) -> None:
        """Say whether a hosted model touched the prompt, and what it would cost."""
        manifest = self._state.manifest
        if manifest is None:
            return
        state = manifest.soundtrack
        enabled, reason = cloud_enabled(self._state.config)
        if state.refinement in ("accepted", "rejected", "failed"):
            self.refine_note.setText(f"Refinement {state.refinement}: {state.refinement_note}")
        elif enabled:
            self.refine_note.setText(
                "Refinement is on: generating sends the signals, never the footage, and "
                "costs one small text request."
            )
        else:
            self.refine_note.setText(f"Refinement is off: {reason}")

    # --- the prompt --------------------------------------------------------

    def generate(self) -> bool:
        """Run the soundtrack stage with the screen's BPM, genre and mood settings.

        Inline when nothing leaves the machine, because the template takes milliseconds
        and the genre box answers as it is turned. On the worker when a hosted model
        refines the prompt, because that is an HTTP request and the window would freeze
        for as long as it takes. True means done, or started on the worker.
        """
        state = self._state
        manifest = state.manifest
        if manifest is None or state.is_running:
            return False
        config = state.config
        genre = self.genre_box.currentData()
        genre_override = str(genre) if genre else None
        bpm = self.bpm_field.value()
        provider = self._provider()
        if provider is None:
            result = build_soundtrack(
                manifest,
                config,
                bpm_override=bpm,
                genre_override=genre_override,
                geocode=False,
            )
            return self._after_generate(result)

        def work(progress: ProgressCallback) -> SoundtrackResult:
            return build_soundtrack(
                manifest,
                config,
                provider=provider,
                progress=progress,
                bpm_override=bpm,
                genre_override=genre_override,
                geocode=False,
            )

        return state.run_stage("soundtrack", work)

    def _after_generate(self, result: SoundtrackResult) -> bool:
        """Show what generation produced. On the UI thread, whichever path it took."""
        state = self._state
        manifest = state.manifest
        if manifest is None:
            return False
        if result.skipped_reason:
            self.matched_label.setText(result.skipped_reason)
            return False
        self._generated = [item for item in manifest.soundtrack.variants if item.source != "user"]
        self._apply_mood_to_variants()
        self._describe_match()
        self._set_variants(manifest.soundtrack.variants)
        self._describe_refinement()
        state.schedule_save()
        self.refresh_preview()
        return True

    def _provider(self) -> TextProvider | None:
        """A text provider when the cloud is on and a key exists, else nothing.

        Built here rather than in the state because it is the only screen that refines,
        and the provider closes over a network client that should not outlive the call.
        """
        enabled, _reason = cloud_enabled(self._state.config)
        if not enabled:
            return None
        key = find_key()
        if key is None:
            return None
        from autocut.core.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(key, self._state.config)

    def _apply_mood_to_variants(self) -> None:
        """Rewrite the generated variants at the current mood positions.

        Always from the pristine generated set, never from the last move: applied to
        their own output, "as matched" would leave whatever the previous position chose
        and two moves in the same direction would compound.
        """
        manifest = self._state.manifest
        if manifest is None:
            return
        calm = MOOD_POSITIONS[self.mood_box.currentIndex()]
        room = ROOM_POSITIONS[self.room_box.currentIndex()]
        kept = [item for item in manifest.soundtrack.variants if item.source == "user"]
        pristine = self._generated or [
            item for item in manifest.soundtrack.variants if item.source != "user"
        ]
        if calm == "keep" and room == "keep":
            manifest.soundtrack.variants = [*kept, *pristine]
            return
        row = self._matched_row()
        signals = manifest.soundtrack.signals
        if row is None or signals is None:
            return
        bpm = int(manifest.soundtrack.proposed_bpm or self.bpm_field.value())
        moved = [
            apply_mood(variant, row, bpm, signals, self._state.config, calm=calm, room=room)
            for variant in pristine
        ]
        # A hand written prompt is not the slider's to rewrite, and it stays first.
        manifest.soundtrack.variants = [*kept, *moved]

    def _matched_row(self) -> GenreRow | None:
        manifest = self._state.manifest
        if manifest is None or manifest.soundtrack.matched_row is None:
            return None
        return next(
            (
                row
                for row in self._state.config.soundtrack.genres
                if row.name == manifest.soundtrack.matched_row
            ),
            None,
        )

    def _mood_changed(self) -> None:
        """A mood move is a regeneration inside the matched row, never a new genre.

        A hand edited variant is left exactly as it was, and the screen says so rather
        than appearing to do nothing: the controls rewrite the generated variants, and
        the prompt somebody typed is not theirs to rewrite.
        """
        manifest = self._state.manifest
        if manifest is None or not manifest.soundtrack.variants:
            return
        self._apply_mood_to_variants()
        self._set_variants(manifest.soundtrack.variants)
        self._state.schedule_save()
        if manifest.soundtrack.variants[self.variant_box.currentIndex()].source == "user":
            self.editor.problems.setText(
                "Your edit is unchanged: the mood controls rewrote the generated "
                "variants. Switch variant to see them."
            )
        self._state.schedule_save()

    def _regenerate_from_controls(self) -> None:
        manifest = self._state.manifest
        if manifest is None or not manifest.soundtrack.variants:
            return
        if self._state.is_running:
            # Applied once when the stage ends, instead of a "still running" error for
            # every turn of the genre box during a refinement.
            self._regenerate_pending = True
            return
        self.generate()

    def _variant_chosen(self, index: int) -> None:
        manifest = self._state.manifest
        if manifest is None or index < 0 or index >= len(manifest.soundtrack.variants):
            return
        manifest.soundtrack.chosen_variant = index
        self.editor.show_variant(manifest.soundtrack.variants[index])
        self._state.schedule_save()

    def _prompt_edited(self) -> None:
        self.save_edit_button.setEnabled(True)

    def store_edit(self) -> bool:
        """Keep what is in the boxes as the chosen variant, if the validator passes."""
        manifest = self._state.manifest
        if manifest is None or self._state.is_running:
            return False
        self.editor.revalidate()
        verdict = store_user_variant(manifest, self.editor.as_variant(), self._state.config)
        if not verdict.ok:
            self.editor.problems.setText(
                "Not kept: "
                + "; ".join(
                    f"{v.rule} on line {v.line}" if v.line else v.rule for v in verdict.violations
                )
            )
            return False
        self._set_variants(manifest.soundtrack.variants)
        self._state.schedule_save()
        return True

    def write_file(self) -> Path | None:
        """Write ``suno-prompt.md`` from what the manifest holds now."""
        state = self._state
        manifest = state.manifest
        if manifest is None or state.is_running:
            return None
        result = SoundtrackResult(
            bpm=int(manifest.soundtrack.proposed_bpm or self.bpm_field.value()),
            beat_distance=manifest.soundtrack.beat_distance or 0.0,
            variants=list(manifest.soundtrack.variants),
        )
        path = write_prompt_file(manifest, result)
        manifest.soundtrack.prompt_path = path
        state.save_now()
        self.prompt_written.emit(str(path))
        return path

    # --- the track ---------------------------------------------------------

    def _browse_track(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(self, "Load a track", "", AUDIO_FILTER)
        if name:
            self.load_track(Path(name))

    def load_track(self, path: Path) -> bool:
        """Decode and measure on the worker; ``track_loaded`` says when it is on screen.

        Beat tracking a whole song takes seconds, which is a frozen window on the UI
        thread. True means the stage started.
        """
        state = self._state
        manifest = state.manifest
        if manifest is None:
            return False
        output_dir = Path(manifest.output_dir)

        def work(_progress: ProgressCallback) -> TrackLoad:
            try:
                samples = decode_audio(path)
                track = measure_track(samples)
            except AudioUnavailableError as error:
                return TrackLoad(path=path, error=str(error))
            pairs = load_or_build_envelope(samples, output_dir, path)
            return TrackLoad(path=path, track=track, pairs=pairs)

        return state.run_stage("track", work)

    def _after_track(self, load: TrackLoad) -> None:
        """Draw the measured track and record it. The manifest is written only here."""
        state = self._state
        manifest = state.manifest
        # The window may have been closed, and the project with it, while the track
        # was being measured.
        if manifest is None:
            self.track_loaded.emit(False)
            return
        track = load.track
        if track is None or load.pairs is None:
            self.track_label.setText(load.error or f"{load.path.name} could not be loaded")
            self.waveform.clear()
            self.apply_button.setEnabled(False)
            self.play_with_track_button.setEnabled(False)
            self.track_loaded.emit(False)
            return
        path = load.path
        self._track = track
        self._audio = path
        self.waveform.set_track(load.pairs, track.beats_s, track.duration_s)
        self.track_label.setText(
            f"{path.name}  {track.duration_s:.1f} s  "
            f"measured {track.bpm:g} bpm from {len(track.beats_s)} beats"
        )
        manifest.soundtrack.audio_path = path
        manifest.soundtrack.measured_bpm = track.bpm
        manifest.soundtrack.beats_s = list(track.beats_s)
        self._describe_comparison(track)
        self.apply_button.setEnabled(True)
        # Loading a track can only take this button away: the clips are cut to whatever
        # the last sync used, and that is not this track until Apply says so.
        self.play_with_track_button.setEnabled(self._synced_with_a_track())
        # Forced: this is the stage's completion handler, so the worker has stopped
        # writing, and the state's own save ran before these fields were set.
        state.save_now(force=True)
        self.refresh_preview()
        self.track_loaded.emit(True)

    def _describe_comparison(self, track: Track) -> None:
        manifest = self._state.manifest
        if manifest is None:
            return
        proposed = manifest.soundtrack.proposed_bpm
        comparison = compare_bpm(proposed, track.bpm, self._state.config.soundtrack.bpm_tolerance)
        manifest.soundtrack.comparison = comparison.status
        manifest.soundtrack.comparison_note = comparison.note
        self.comparison_label.setText(comparison.note or "")
        drifted = comparison.status in ("drifted", "half", "double")
        self.comparison_label.setProperty("role", "warning" if drifted else None)
        theme.repolish(self.comparison_label)
        if comparison.status in ("half", "double") and proposed:
            # The tracker's usual mistake, and the fix is one field away.
            self.override_field.blockSignals(True)
            self.override_field.setValue(float(proposed))
            self.override_field.blockSignals(False)

    def _synced_with_a_track(self) -> bool:
        """Whether the clips on disk were cut to the track that is loaded now.

        Any clip carrying beats used to be enough, and it is not: a project synced to
        yesterday's click still carries them, so loading a new track let the montage
        render yesterday's bounds against today's music with every number on screen
        agreeing. The manifest now says which track and tempo the bounds came from.
        """
        manifest = self._state.manifest
        if manifest is None or self._audio is None:
            return False
        if not any(segment.beats is not None for segment in manifest.segments.values()):
            return False
        return synced_against(manifest, self.effective_bpm(), self._audio)

    def _override_changed(self) -> None:
        """A new tempo is a new set of bounds, so the synced edit is no longer this one."""
        self.refresh_preview()
        self.play_with_track_button.setEnabled(self._synced_with_a_track())

    def effective_bpm(self) -> float:
        """What Apply would use: the override when set, otherwise the measurement."""
        override = self.override_field.value()
        if override > 0:
            return float(override)
        return self._track.bpm if self._track is not None else 0.0

    def refresh_preview(self) -> None:
        """What this tempo would do to the edit, without touching a segment."""
        manifest = self._state.manifest
        bpm = self.effective_bpm()
        if manifest is None or bpm <= 0:
            self.distribution_label.setText("")
            self._preview = None
            return
        result = quantize_durations(manifest, bpm, self._state.config, dry_run=True)
        self._preview = result
        if not result.clips:
            self.distribution_label.setText("Nothing selected to sync.")
            return
        spread = ", ".join(
            f"{count} x {multiple}" for multiple, count in result.per_multiple.items()
        )
        lines = [
            f"At {bpm:g} bpm: {result.clips} clips, "
            f"{result.total_before_s:.1f} s becomes {result.total_after_s:.1f} s "
            f"({result.drift_s:+.1f} s)",
            f"beats per clip: {spread}",
        ]
        if result.clamped:
            lines.append(f"{result.clamped} clips would be clamped by their own span")
        self.distribution_label.setText("\n".join(lines))

    def apply_sync(self) -> bool:
        """Run beat sync through the worker at the effective BPM."""
        state = self._state
        manifest = state.manifest
        bpm = self.effective_bpm()
        if manifest is None or self._track is None or bpm <= 0 or state.is_running:
            return False
        config = state.config
        track = self._track
        override = self.override_field.value()
        output_dir = Path(manifest.output_dir)

        audio = self._audio
        assert audio is not None  # _track is only set with an audio path beside it

        def work(progress: ProgressCallback) -> QuantizeResult:
            reset_final_bounds(manifest)
            result = quantize_durations(manifest, bpm, config, progress)
            manifest.soundtrack.bpm_override = float(override) if override > 0 else None
            manifest.soundtrack.beatmap_path = write_beatmap(manifest, track, output_dir)
            # Last, and only here: what the bounds on the clips were actually made
            # from. Everything before this line is a measurement.
            record_sync(manifest, bpm, audio)
            progress(ProgressEvent(stage="sync", current=result.clips, total=result.clips))
            return result

        return state.run_stage("sync", work)

    # --- reacting ----------------------------------------------------------

    def play_with_track(self) -> bool:
        """Watch the synced edit with the music on it, so the drift is heard.

        The montage is rendered with the track muxed, which is the only way to hear
        whether the cuts land: a beat grid that is subtly wrong looks right and sounds
        wrong, and this screen exists to catch that before an export.
        """
        state = self._state
        manifest = state.manifest
        if manifest is None or state.is_running:
            return False
        # The button is disabled without a finished sync, and the method refuses too:
        # it is public, and a montage of clips that are not on the grid would be a
        # preview of the wrong thing.
        if not self._synced_with_a_track():
            self.distribution_label.setText(
                "Apply sync first: the clips are not on the beat grid yet."
            )
            return False
        track = self._audio
        if state.montage_is_current(track) and self._show_montage():
            self.montage.play()
            return True
        # The same reason as the Review screen: the player holds the file open.
        self.montage.clear()
        self.distribution_label.setText("Building the montage with the track…")
        return state.run_montage(track=track)

    def _show_montage(self) -> bool:
        manifest = self._state.manifest
        if manifest is None or manifest.preview.path is None:
            return False
        path = Path(manifest.preview.path)
        index = Path(manifest.preview.index_path) if manifest.preview.index_path else None
        if not self.montage.load(
            path,
            index,
            sound=manifest.preview.has_audio,
            labels=clip_labels(manifest),
        ):
            return False
        self.montage.setVisible(True)
        return True

    def _stage_finished(self, name: str) -> None:
        self._set_running(False)
        if name == "track":
            load = self._state.last_result
            if isinstance(load, TrackLoad):
                self._after_track(load)
            return
        if name == "soundtrack":
            result = self._state.last_result
            if isinstance(result, SoundtrackResult):
                self._after_generate(result)
                # The state saved before the mood moves above; save what is on screen.
                self._state.save_now(force=True)
            return
        if name == "montage":
            result = self._state.last_result
            if isinstance(result, MontageResult) and result.ok and self._show_montage():
                self.montage.play()
                discard(result.previous)
            elif isinstance(result, MontageResult):
                self.distribution_label.setText(
                    result.skipped_reason or "The montage could not be built."
                )
            return
        if name != "sync":
            return
        result = self._state.last_result
        if isinstance(result, QuantizeResult):
            self.distribution_label.setText(
                f"Synced {result.clips} clips at {result.bpm:g} bpm, "
                f"{result.total_after_s:.1f} s of edit, mean move {result.mean_shift_s:.2f} s"
            )
        # A finished sync, not merely a loaded track: hearing the cuts against the
        # music is the point, and a sync that failed or was cancelled leaves the clips
        # off the grid with nothing to hear.
        self.play_with_track_button.setEnabled(self._synced_with_a_track())
        self.synced.emit()

    def _stage_ended(self, _name: str) -> None:
        """Apply a genre or BPM change that arrived during a generation, once.

        Here rather than on ``stage_finished``, which arrives while the worker may still
        be winding down and would refuse the new run. Dropped after a cancel: that is
        the window closing or the user stopping the stage, and neither asked for more.
        """
        state = self._state
        if not self._regenerate_pending or state.is_running:
            return
        self._regenerate_pending = False
        if not state.cancel_requested:
            self.generate()

    def _set_running(self, running: bool) -> None:
        for widget in (
            self.generate_button,
            self.save_edit_button,
            self.write_button,
            self.apply_button,
            self.play_with_track_button,
            self.load_button,
            self.editor,
        ):
            widget.setEnabled(not running)
        if not running:
            self.apply_button.setEnabled(self._track is not None)
            self.play_with_track_button.setEnabled(self._synced_with_a_track())
