# Instrument Translation

A computer-vision project exploring a virtual piano played on paper using a phone camera, OpenCV, and MediaPipe.

## Requirements

- Python 3.12
- `pip`
- A phone with a camera and browser
- [ngrok](https://ngrok.com/download) for HTTPS camera access

## Setup

Clone the repository:

```powershell
git clone <repository-url>
cd Instrument-Translation
```

Make sure Python 3.12 is selected as the project interpreter. In VS Code, use
**Python: Select Interpreter** and choose the Python 3.12 interpreter (or the
project's `.venv` after creating it). In PowerShell, use `py -3.12` to create
the environment with Python 3.12 even if the `python` command points to a
different installation.

Create and activate a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

After activation, confirm the project environment is being used:

```powershell
python -c "import sys; print(sys.executable)"
```

The printed path should point to `.venv\Scripts\python.exe`.

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

The MediaPipe Hand Landmarker model is included in `models/hand_landmarker.task`.

Install and configure ngrok using its [official documentation](https://ngrok.com/docs/).

## Running

1. Start the server:

   ```powershell
   python phone_server.py
   ```

2. Open a separate terminal and start the HTTPS tunnel:

   ```powershell
   ngrok http 5000
   ```

3. Open the HTTPS forwarding URL displayed by ngrok on your phone.
4. Select **Start Camera** and allow camera access.
5. Press `Q` in the OpenCV window to stop the server.

Keep both the Python server and ngrok running while using the camera.

## Project Structure

- `phone_server.py` — Flask server, frame processing, and hand tracking.
- `phone_camera.html` — Phone camera interface.
- `phone_camera.css` — Interface styling.
- `phone_camera.js` — Camera capture and frame transmission.
- `paper_detector.py` — Paper detection.
- `models/hand_landmarker.task` — MediaPipe hand-tracking model.
- `requirements.txt` — Python dependencies.

## Using the iPhone over USB (no ngrok)

Install **Camo Camera** (iPhone) and **Camo Studio** (Windows, camo.com), plug in the cable, and open both. Then:

```powershell
python phone_server.py --list-cameras    # find Camo's index
python phone_server.py --camera 1        # use that index
```

The free Camo tier (720p) is enough. Without `--camera`, the phone page + ngrok setup above still works.

Tips:
- Use the iPhone's **1×** lens, not 0.5× (the ultra-wide is softer, bends the paper's edges, and makes keys tiny).
- Keep Camo Camera open and the phone unlocked (Auto-Lock → Never while testing); Camo Studio can stay minimised.
- Run one server at a time, from the project `.venv` (select it as VS Code's interpreter).
- Webcam frames are shrunk to 640 px wide for speed. The second status line shows `rx` (frames arriving), `proc` (ms to process one) and `age` (ms from arrival to ready).
- Plug the laptop in and use the **Best performance** power mode: on low battery the CPU throttles and `proc` can jump past 100 ms.
- Q or Ctrl+C quits cleanly.

## Calibration

The template is black solid boxes or black outlines on white Letter paper, landscape.

- Press `C` with your hands out of view; regions are numbered left to right.
- Press `S` to save the current frame to `samples/`.
- `python calibrate_image.py samples/<file>.jpg` writes a `_debug.png` showing the
  flattened paper, the ink mask and the numbered regions.
- The **Calibration settings** window has **Sens** (sensitivity) (raise it if lines are missed, lower it if
  paper texture or shadows become regions) and **Key** (min black key) (lower it for small drawings).
  Changes re-detect instantly.

## Tap Strap (M0)

`tapstrap/` reads raw finger accelerometer data from a Tap Strap 2 (`python stream_raw.py --demo` for a live readout without a strap).

- `python m0_record.py` runs a prompted session (clicks cue each tap) and writes `recordings/m0_<time>_{fingers,imu,cues}.csv`; the columns are documented in the script. Add `--demo` to try it without a strap.
- `python m0_analyze.py recordings/m0_<time>` writes `_report.txt` and `_report.png` (stream health, per-finger separability, crosstalk, a simple detector's precision/recall).

## Tests

Run the unit tests from the repo root:

```
python -m unittest discover -s tests -t .
```

## Notes

- Phone camera access requires HTTPS; use the ngrok forwarding URL.
- Do not commit `.venv/`, authentication tokens, or other secrets.
