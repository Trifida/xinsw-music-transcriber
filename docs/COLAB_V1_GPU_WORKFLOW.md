# V1 Google Colab GPU workflow

Last updated: 2026-11-25

## Current execution policy

- Google Colab is the only GPU execution environment for V1 development and acceptance testing.
- Use a GPU runtime already assigned by Colab. If Colab does not provide a GPU, stop GPU inference and report the runtime state; do not rent, provision, or start a paid GPU.
- Do not use AutoDL provisioning, paid-GPU dispatch, automatic GPU startup, or automatic paid-GPU release as part of the current V1 workflow.
- Paid GPU hosting is a later commercial deployment decision, after V1 passes real-audio and end-to-end acceptance.
- Keep source code in `Trifida/xinsw-music-transcriber`; keep the canonical shared notebook, models, audio fixtures, and benchmark outputs in the user's Google Drive.
- Do not treat an installed Python package or a generated MIDI file as proof that the corresponding model pipeline works.

## Read-only preflight

The first action in a fresh Colab runtime is an environment inventory. It must not install or upgrade dependencies, download models, start inference, or change Drive contents.

From the repository checkout, run:

```bash
python scripts/colab_v1_preflight.py
```

The script reports:

- Python executable/version and platform;
- PyTorch version, CUDA build, CUDA availability, GPU model and memory;
- TensorFlow version and visible GPUs;
- key package versions and import availability;
- Google Drive mount state and known model/data directories;
- BS-RoFormer checkpoint, YAML and download-check file presence;
- current repository branch, commit and working-tree status when Git metadata exists.

The script only prints a JSON report. It does not write a report file unless the user explicitly redirects the output.

## Known historical observations (not current runtime guarantees)

- A Colab T4 with approximately 15 GB VRAM was previously observed.
- One earlier session reported PyTorch `2.14.1+cu130`, CUDA available, and a successful `audio_separator` import.
- The BS-RoFormer checkpoint was found in Drive at:
  `/content/drive/MyDrive/XinsW_Models/BS-RoFormer/model_bs_roformer_ep_317_sdr_12.9755.ckpt`
  with a matching YAML configuration and `download_checks.json`.
- Other sessions reported Python 3.13 and differing TensorFlow/PyTorch states. These are historical snapshots, not a reproducible environment specification.

## Dependency safety

The current repository has a legacy transcription dependency pin to TensorFlow 2.15.0. Do not blindly install the full requirements into the current Colab interpreter: first compare Python, TensorFlow, NumPy, PyTorch and CUDA versions. In particular, a Python 3.12+ runtime must not be assumed compatible with the TensorFlow 2.15.0 pin.

If a separate compatible Python environment is needed, design and test that environment as a separate step. Do not replace Colab's preinstalled PyTorch/CUDA stack during the read-only inventory.

## V1 validation order

1. Confirm Colab GPU availability and model-file integrity.
2. Reproduce BS-RoFormer separation on a known real mixed recording.
3. Listen to and inspect both vocal and instrumental stems; document residual reverb, backing vocals and bleed.
4. Run CREPE on the separated lead-vocal stem, not on the original full mix.
5. Evaluate pitch, octave, note boundaries, rhythm, rests and phrase boundaries against a manually checked reference.
6. Run key analysis without changing the source pitches.
7. Generate MusicXML, MIDI, staff SVG, jianpu SVG/PDF from the same event data and compare them.
8. Complete manual lyric alignment/edit/save/re-render on the cloud full-song workflow.
9. Repeat the complete upload-to-download workflow on multiple real songs and record runtime, failures and output quality.

ASR and automatic lyric transcription remain V2. Full polyphonic accompaniment transcription is not claimed as a completed V1 feature.

## Handoff requirements

For every Colab test, preserve the JSON preflight output and record:

- notebook name and the exact cell(s) run;
- repository branch and commit;
- GPU model and VRAM;
- Python, PyTorch, CUDA, TensorFlow and key audio package versions;
- source audio identifier and audio-quality notes;
- model checkpoint/configuration and hashes when available;
- elapsed time, peak memory when measurable, and generated artifacts;
- manual quality findings and unresolved errors.

Do not mark a feature commercially ready until real-audio results and the complete user workflow have passed acceptance.
