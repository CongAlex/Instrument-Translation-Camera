const video = document.getElementById("video");
const status = document.getElementById("status");
const resolution = document.getElementById("resolution");
const startButton = document.getElementById("start");
const stopButton = document.getElementById("stop");
const fpsLabel = document.getElementById("fps-label");
const fpsBar = document.getElementById("fps-bar");

const canvas = document.createElement("canvas");
const context = canvas.getContext("2d");

let stream = null;
let timer = null;
let inFlight = 0;
const MAX_IN_FLIGHT = 2;
let running = false;

let successfulFrames = 0;
let lastFpsUpdate = performance.now();
let rttMs = 0;

function resetFps() {
    successfulFrames = 0;
    lastFpsUpdate = performance.now();
    rttMs = 0;

    fpsLabel.textContent = "Sending FPS: 0.0";
    fpsBar.style.width = "0%";
    fpsBar.style.background = "#dc3545";
}

function updateFps() {
    successfulFrames++;

    const now = performance.now();
    const elapsed = now - lastFpsUpdate;

    if (elapsed < 500) {
        return;
    }

    const fps = successfulFrames * 1000 / elapsed;

    fpsLabel.textContent = `Sending FPS: ${fps.toFixed(1)} · RTT ${rttMs.toFixed(0)} ms`;

    const percentage = Math.min((fps / 30) * 100, 100);
    fpsBar.style.width = percentage + "%";

    if (fps >= 20) {
        fpsBar.style.background = "#28a745";
    } else if (fps >= 10) {
        fpsBar.style.background = "#ffc107";
    } else {
        fpsBar.style.background = "#dc3545";
    }

    successfulFrames = 0;
    lastFpsUpdate = now;
}

async function sendFrame() {
    if (
        !running ||
        inFlight >= MAX_IN_FLIGHT ||
        video.readyState < 2 ||
        !canvas.width ||
        !canvas.height
    ) {
        return;
    }

    inFlight++;

    try {
        context.drawImage(
            video,
            0,
            0,
            canvas.width,
            canvas.height
        );

        const blob = await new Promise(resolve => {
            canvas.toBlob(resolve, "image/jpeg", 0.7);
        });

        if (!blob || !running) {
            return;
        }

        const sentAt = performance.now();
        const response = await fetch("/frame", {
            method: "POST",
            headers: {
                "Content-Type": "application/octet-stream"
            },
            body: blob
        });

        if (!response.ok) {
            throw new Error("Server returned " + response.status);
        }

        if (running) {
            const elapsed = performance.now() - sentAt;
            rttMs = 0.8 * rttMs + 0.2 * elapsed;
            updateFps();
            status.textContent = "Camera running — frames sending.";
        }
    } catch (error) {
        if (running) {
            status.textContent = "Sending failed: " + error.message;
        }

        console.error(error);
    } finally {
        inFlight--;
    }
}

startButton.addEventListener("click", async () => {
    startButton.disabled = true;
    status.textContent = "Starting camera...";

    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "environment",
                width: { ideal: 640 },
                height: { ideal: 480 },
                frameRate: { ideal: 30 }
            },
            audio: false
        });

        video.srcObject = stream;
        await video.play();

        if (!video.videoWidth || !video.videoHeight) {
            await new Promise(resolve => {
                video.addEventListener("loadedmetadata", resolve, {
                    once: true
                });
            });
        }

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        resolution.textContent =
            `Actual resolution: ${canvas.width} × ${canvas.height}`;

        console.log(
            "Actual resolution:",
            canvas.width,
            "x",
            canvas.height
        );

        running = true;
        resetFps();

        stopButton.disabled = false;
        status.textContent = "Camera started; connecting...";

        // Attempt to send up to 30 frames per second.
        timer = setInterval(sendFrame, 33);
    } catch (error) {
        running = false;

        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }

        video.srcObject = null;
        startButton.disabled = false;

        status.textContent = "Camera error: " + error.message;
        console.error(error);
    }
});

stopButton.addEventListener("click", () => {
    running = false;

    if (timer !== null) {
        clearInterval(timer);
        timer = null;
    }

    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }

    video.srcObject = null;

    startButton.disabled = false;
    stopButton.disabled = true;

    status.textContent = "Camera stopped.";
    resolution.textContent = "Resolution: not started";

    resetFps();
});