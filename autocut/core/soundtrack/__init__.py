"""Writing the music prompt from the finished edit (SPEC.md section 7.5).

Split by what each part answers. :mod:`signals` says what the edit is, :mod:`genres`
picks the row that describes it, :mod:`prompt` writes the blocks and proposes a BPM,
:mod:`validate` is the one gate every prompt passes through whoever wrote it, and
:mod:`refine` optionally asks a hosted model to say it better.
"""
