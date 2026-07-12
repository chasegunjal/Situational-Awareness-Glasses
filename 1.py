from flask import Flask, Response
import subprocess
import numpy as np
import cv2
import threading
import time

app = Flask(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
ISO_FACTOR = 1.2        # Digital ISO for cam1 (1.0 = normal, 2.0 = very bright)
WIDTH      = 640
HEIGHT     = 360
FRAMERATE  = 20

# ─────────────────────────────────────────────
# SHARED STATE
# ─────────────────────────────────────────────
frame_lock   = threading.Lock()
output_frame = None     # raw JPEG bytes from camera
current_cam  = 0
proc         = None


# ─────────────────────────────────────────────
# IMAGE PROCESSING (from image_processing.py)
# Only applied when cam1 is active
# ─────────────────────────────────────────────
def apply_digital_iso(frame, iso_factor):
    """Simulate ISO gain — brightens/darkens the frame."""
    frame = frame.astype(np.float32) * iso_factor
    return np.clip(frame, 0, 255).astype(np.uint8)

def denoise(frame):
    """Basic Gaussian blur noise reduction."""
    return cv2.GaussianBlur(frame, (5, 5), 0)


# ─────────────────────────────────────────────
# CAMERA PROCESS
# ─────────────────────────────────────────────
def start_camera(cam_id):
    return subprocess.Popen([
        "rpicam-vid",
        "--camera", str(cam_id),
        "-t", "0",
        "--width",     str(WIDTH),
        "--height",    str(HEIGHT),
        "--framerate", str(FRAMERATE),
        "--codec",     "mjpeg",
        "--nopreview",
        "-o", "-"
    ], stdout=subprocess.PIPE)


# ─────────────────────────────────────────────
# CAMERA THREAD (single producer)
# ─────────────────────────────────────────────
def camera_thread():
    global output_frame, proc

    proc   = start_camera(current_cam)
    buffer = b""

    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            continue

        buffer += chunk
        start = buffer.find(b'\xff\xd8')
        end   = buffer.find(b'\xff\xd9')

        if start != -1 and end != -1:
            jpg    = buffer[start:end + 2]
            buffer = buffer[end + 2:]

            with frame_lock:
                output_frame = jpg

        time.sleep(0.005)


# ─────────────────────────────────────────────
# STREAM GENERATORS
# ─────────────────────────────────────────────

def generate_frames():
    """
    Normal stream.
    - cam0 (no-IR / night vision): raw JPEG, no processing
    - cam1 (normal camera):        OpenCV processed (ISO + denoise)
    """
    global output_frame

    while True:
        with frame_lock:
            if output_frame is None:
                time.sleep(0.01)
                continue
            jpg = output_frame

        if current_cam == 1:
            # ── Apply OpenCV processing for cam1 ──
            frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            frame = apply_digital_iso(frame, ISO_FACTOR)
            frame = denoise(frame)
            _, buf = cv2.imencode('.jpg', frame)
            jpg = buf.tobytes()
        # cam0: pass raw JPEG through, no processing

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')


# VR config — tune these to match your headset
VR_EYE_W    = 640    # width of each eye panel
VR_EYE_H    = 380    # height of each eye panel
VR_SEP      = 40     # black separator width in pixels (adjust for your lens gap)

# Pre-allocate separator once
_vr_separator = np.zeros((VR_EYE_H, VR_SEP, 3), dtype=np.uint8)

def generate_vr_frames():
    """
    VR side-by-side stream with black separator and proper eye sizing.
    - cam0: raw frame (night vision)
    - cam1: OpenCV processed (ISO + denoise)
    Final frame = [left_eye | separator | right_eye]
    Resolution  = (VR_EYE_W*2 + VR_SEP) x VR_EYE_H
    """
    global output_frame

    while True:
        with frame_lock:
            if output_frame is None:
                time.sleep(0.01)
                continue
            jpg = output_frame

        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        # Resize to exact VR eye dimensions first
        eye = cv2.resize(frame, (VR_EYE_W, VR_EYE_H),
                         interpolation=cv2.INTER_LINEAR)

        if current_cam == 1:
            eye = apply_digital_iso(eye, ISO_FACTOR)
            eye = denoise(eye)

        # Build: left eye | black bar | right eye
        vr_frame = np.hstack((eye, _vr_separator, eye))

        _, buf = cv2.imencode('.jpg', vr_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    cam_label = "🌙 cam0 — Night Vision (no-IR)" if current_cam == 0 else "📷 cam1 — Normal (OpenCV active)"
    return f"""
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          body {{ margin:0; background:black; display:flex; flex-direction:column;
                  justify-content:center; align-items:center; height:100vh; color:white; font-family:sans-serif; }}
          .badge {{ background:#222; padding:6px 14px; border-radius:20px; font-size:13px; margin-bottom:10px; }}
          .links {{ position:absolute; bottom:20px; text-align:center; }}
          a {{ color:cyan; margin:0 8px; text-decoration:none; }}
          a.cam {{ color:yellow; }}
        </style>
      </head>
      <body>
        <div class="badge">{cam_label}</div>
        <img src="/video" style="max-width:100%; max-height:85vh; object-fit:contain;">
        <div class="links">
          <a href="/vr">🥽 VR Mode</a><br><br>
          <button onclick="captureFrame()" style="
            background:#1a1a2e;
            color:white;
            border:2px solid cyan;
            padding:10px 24px;
            border-radius:24px;
            font-size:14px;
            cursor:pointer;
            margin-bottom:10px;
          ">📸 Capture Frame</button><br><br>
          <a class="cam" href="/switch/0">Camera 0 (Night)</a> |
          <a class="cam" href="/switch/1">Camera 1 (Normal)</a>
        </div>

        <script>
          function captureFrame() {{
            fetch('/capture')
              .then(r => r.blob())
              .then(blob => {{
                const url = URL.createObjectURL(blob);
                const a   = document.createElement('a');
                a.href    = url;
                a.download = 'capture_' + Date.now() + '.jpg';
                a.click();
                URL.revokeObjectURL(url);
              }});
        }}
        </script>
      </body>
    </html>
    """


@app.route('/vr')
def vr():
    cam_label = "🌙 Night Vision VR" if current_cam == 0 else "📷 Normal VR (OpenCV active)"
    return f"""<!DOCTYPE html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ margin:0; padding:0; box-sizing:border-box; }}
      body {{ background:black; display:flex; justify-content:center;
              align-items:center; height:100vh; overflow:hidden; }}
      #vr-img {{ width:80vw; height:40vh; object-fit:fill; display:block; }}
      .overlay {{ position:fixed; top:12px; left:50%; transform:translateX(-50%);
                  color:white; background:rgba(0,0,0,0.5); padding:5px 14px;
                  border-radius:20px; font-size:12px; font-family:sans-serif;
                  z-index:10; transition:opacity 2s; }}
      .back {{ position:fixed; bottom:16px; left:50%; transform:translateX(-50%);
               color:cyan; font-family:sans-serif; font-size:13px; z-index:10;
               background:rgba(0,0,0,0.5); padding:5px 14px; border-radius:20px;
               text-decoration:none; transition:opacity 2s; }}
      #capbtn {{ position:fixed; bottom: 70px; right: 380px;
                 background:rgba(0,0,0,0.5); color:white;
                 border:2px solid cyan; padding:8px 18px;
                 border-radius:24px; font-size:13px; font-family:sans-serif;
                 cursor:pointer; z-index:10; transition:opacity 2s; }}
    </style>
  </head>
  <body>
    <div class="overlay" id="label">{cam_label}</div>
    <img id="vr-img" src="/video_vr">
    <a class="back" id="back" href="/">← Exit VR</a>
    <button id="capbtn" onclick="captureFrame()">📸</button>

    <script>
      // ── Fullscreen ───────────────────────────────
      function goFullscreen() {{
        const el = document.documentElement;
        if (el.requestFullscreen) el.requestFullscreen();
        else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        else if (el.mozRequestFullScreen) el.mozRequestFullScreen();
      }}
      document.addEventListener('DOMContentLoaded', goFullscreen);
      document.body.addEventListener('click', goFullscreen);

      // ── Hide UI after 4 seconds ──────────────────
      let timer;
      const lbl    = document.getElementById('label');
      const back   = document.getElementById('back');
      const capbtn = document.getElementById('capbtn');

      function resetTimer() {{
        lbl.style.opacity = back.style.opacity = capbtn.style.opacity = '1';
        clearTimeout(timer);
        timer = setTimeout(() => {{
          lbl.style.opacity = back.style.opacity = capbtn.style.opacity = '0';
        }}, 4000);
      }}
      document.addEventListener('touchstart', resetTimer);
      document.addEventListener('mousemove',  resetTimer);
      resetTimer();

      // ── Sensors ─────────────────────────────────
      let currentCam = {current_cam};

      function switchCam(id) {{
        fetch('/nav', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{action: 'switch', cam: id}})
        }}).then(r => r.json()).then(d => {{
          if (d.status === 'ok') {{
            currentCam = id;
            lbl.textContent = id === 0 ? '🌙 Night Vision VR' : '📷 Normal VR (OpenCV active)';
            resetTimer();
          }}
        }});
      }}

      // Gyroscope → head tracking
      window.addEventListener('deviceorientation', (e) => {{
        document.getElementById('vr-img').style.transform =
          `rotateY(${{(e.gamma || 0) * 0.3}}deg) rotateX(${{-(e.beta || 0) * 0.2}}deg)`;
      }});

      // Accelerometer → shake to switch camera
      let lastShake = 0;
      window.addEventListener('devicemotion', (e) => {{
        const a = e.accelerationIncludingGravity;
        if (!a) return;
        const mag = Math.hypot(a.x, a.y, a.z);
        const now = Date.now();
        if (mag > 25 && now - lastShake > 2000) {{
          lastShake = now;
          switchCam(currentCam === 0 ? 1 : 0);
        }}
      }});

      // Ambient light → auto switch
      if ('AmbientLightSensor' in window) {{
        try {{
          const s = new AmbientLightSensor();
          s.addEventListener('reading', () => {{
            const t = s.illuminance < 50 ? 0 : 1;
            if (t !== currentCam) switchCam(t);
          }});
          s.start();
        }} catch(e) {{ console.warn('Light sensor:', e); }}
      }}

      // ── Capture button ───────────────────────────
      function captureFrame() {{
        fetch('/capture')
          .then(r => r.blob())
          .then(blob => {{
            const url = URL.createObjectURL(blob);
            const a   = document.createElement('a');
            a.href    = url;
            a.download = 'vr_capture_' + Date.now() + '.jpg';
            a.click();
            URL.revokeObjectURL(url);
            capbtn.textContent = '✅';
            setTimeout(() => capbtn.textContent = '📸', 1500);
          }});
      }}
    </script>
  </body>
</html>"""

@app.route('/video')
def video():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video_vr')
def video_vr():
    return Response(generate_vr_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/switch/<int:cam_id>')
def switch(cam_id):
    global proc, current_cam

    if cam_id not in (0, 1):
        return "Invalid camera ID. Use 0 or 1.", 400

    if proc:
        proc.kill()
        proc = None

    current_cam = cam_id
    proc = start_camera(cam_id)

    label = "Night Vision (no-IR, raw)" if cam_id == 0 else "Normal (OpenCV: ISO + denoise active)"
    return f"Switched to Camera {cam_id} — {label}. <a href='/'>Go back</a>"

@app.route('/capture')
def capture():
    from flask import send_file
    import io

    with frame_lock:
        jpg = output_frame

    if jpg is None:
        return "No frame available", 503

    if current_cam == 1:
        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frame = apply_digital_iso(frame, ISO_FACTOR)
            frame = denoise(frame)
            _, buf = cv2.imencode('.jpg', frame)
            jpg = buf.tobytes()

    return send_file(
        io.BytesIO(jpg),
        mimetype='image/jpeg',
        as_attachment=True,
        download_name=f'capture_{int(time.time())}.jpg'
    )
# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    t = threading.Thread(target=camera_thread, daemon=True)
    t.start()

    print("🚀 Server running at http://<pi-ip>:5000")
    print("📷 cam0 = Night Vision (no-IR) — raw + VR")
    print("📷 cam1 = Normal camera — OpenCV (ISO + denoise) + VR")
    app.run(host='0.0.0.0', port=5000, threaded=True)