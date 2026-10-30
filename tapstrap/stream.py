"""Connect to a Tap Strap 2 and stream raw finger-accelerometer + thumb-IMU data.

Uses TapWithUs' official ``tapsdk`` (tap-python-sdk) for the Bluetooth connection
and raw-mode commands (it also re-sends the mode every 10 s, which the firmware
requires or it falls back to text mode). Decoding is done by ``tapstrap.decode``.

    async with TapRawStream(SensorConfig(finger_accel_g=4)) as tap:
        async for sample in tap.samples():
            ...
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import AsyncIterator, Callable, List, Optional

from .decode import FingerAccelSample, ImuSample, Sample, SensorConfig, decode_notification

log = logging.getLogger(__name__)

SampleCallback = Callable[[Sample, float], None]  # (sample, host_time_s)


class TapRawStream:
    """Async context manager yielding decoded raw samples from a Tap Strap."""

    def __init__(self, config: SensorConfig = SensorConfig(), address: Optional[str] = None,
                 queue_size: int = 4096):
        self.config = config
        self.address = address
        self._sdk = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._callbacks: List[SampleCallback] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.dropped = 0

    def on_sample(self, cb: SampleCallback) -> None:
        """Register a callback fired for every sample (runs on the event loop)."""
        self._callbacks.append(cb)

    # -- lifecycle ---------------------------------------------------------
    async def __aenter__(self) -> "TapRawStream":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        from tapsdk import TapSDK, InputModeRaw
        from tapsdk.enumerations import FingerAcclSensitivity, ImuAcclSensitivity, ImuGyroSensitivity

        self._loop = asyncio.get_running_loop()
        self._sdk = TapSDK(address=self.address)
        # Take over the raw-data notification handler so we get the bytes
        # ourselves (start() binds self.on_raw_data when it subscribes).
        self._sdk.on_raw_data = self._handle_notification

        log.info("Connecting to Tap (make sure it's paired and awake)...")
        await self._sdk.run()
        try:
            info = await self._sdk.get_device_info()
            log.info("Connected: %s  fw=%s  battery=%s%%", info.name, info.fw_version, info.battery_level)
        except Exception as e:  # device info needs a bonded link; not essential
            log.debug("Could not read device info: %s", e)

        f, g, a = self.config.command_bytes
        await self._sdk.set_input_mode(InputModeRaw(
            scaled=False,  # we scale in decode.py
            finger_accl_sens=FingerAcclSensitivity(f),
            imu_gyro_sens=ImuGyroSensitivity(g),
            imu_accl_sens=ImuAcclSensitivity(a),
        ))
        log.info("Raw sensor mode on: fingers ±%dg, gyro ±%ddps, thumb accel ±%dg",
                 self.config.finger_accel_g, self.config.imu_gyro_dps, self.config.imu_accel_g)

    async def stop(self) -> None:
        if self._sdk is None:
            return
        from tapsdk import InputModeText
        sdk, self._sdk = self._sdk, None
        try:
            await sdk.input_mode_refresh.stop()
            # Put the strap back to normal typing mode before leaving.
            await sdk._write_input_mode(InputModeText().get_command())
        except Exception as e:
            log.debug("Could not restore text mode: %s", e)
        try:
            await sdk.client.disconnect()
        except Exception as e:
            log.debug("Disconnect error: %s", e)
        log.info("Disconnected.")

    # -- data path ---------------------------------------------------------
    def _handle_notification(self, _char, data: bytearray) -> None:
        now = time.time()
        for s in decode_notification(bytes(data), self.config):
            self._emit(s, now)

    def _emit(self, sample: Sample, host_time: float) -> None:
        for cb in self._callbacks:
            try:
                cb(sample, host_time)
            except Exception:
                log.exception("sample callback failed")
        try:
            self._queue.put_nowait((sample, host_time))
        except asyncio.QueueFull:
            self.dropped += 1  # nobody is consuming samples(); keep newest by dropping

    async def samples(self) -> AsyncIterator[Sample]:
        """Async iterator over samples (FingerAccelSample or ImuSample)."""
        while True:
            sample, _ = await self._queue.get()
            yield sample


class DemoStream(TapRawStream):
    """Synthetic stand-in with the same interface, for testing without hardware.

    Fingers "tap" in turn; the thumb IMU slowly rotates.
    """

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        log.info("Demo stream started (no hardware).")

    async def stop(self) -> None:
        self._task.cancel()

    async def _run(self) -> None:
        t0 = time.time()
        k = 0
        while True:
            t = time.time() - t0
            ms = int(t * 1000)
            vecs = []
            for i in range(5):
                phase = (t * 2 - i * 0.4) % 2.0
                spike = 2.5 * math.exp(-((phase - 0.1) / 0.02) ** 2)
                vecs.append((0.05 * math.sin(t + i), 0.05 * math.cos(t + i), -1.0 - spike))
            now = time.time()
            self._emit(FingerAccelSample(ms, *vecs), now)
            self._emit(ImuSample(ms, (30 * math.sin(t), 20 * math.cos(t * 0.7), 5.0),
                                 (math.sin(t * 0.5) * 0.3, 0.0, -1.0)), now)
            k += 1
            await asyncio.sleep(max(0.0, t0 + k / 200 - time.time()))
