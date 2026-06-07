# coding: utf-8

import os
import subprocess
import threading
import time


class AudioPlayer:
    def __init__(self, on_play_end=None):
        self._proc = None
        self._lock = threading.Lock()
        self._on_play_end = on_play_end
        self._last_end_time = 0.0

    def set_on_play_end(self, callback):
        self._on_play_end = callback

    def is_playing(self):
        with self._lock:
            proc = self._proc
        return bool(proc and proc.poll() is None)

    def seconds_since_end(self):
        with self._lock:
            last_end_time = self._last_end_time
        if not last_end_time:
            return None
        return time.time() - last_end_time

    def play(self, path):
        if not path or not os.path.exists(path):
            return False, "audio path not found"
        self.stop()
        with self._lock:
            command = ["play", "-q", path]
            try:
                self._proc = subprocess.Popen(command)
            except Exception:
                self._proc = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])
            thread = threading.Thread(target=self._wait_for_end)
            thread.setDaemon(True)
            thread.start()
        return True, "playing"

    def stop(self):
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            deadline = time.time() + 1.0
            while proc.poll() is None and time.time() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                proc.kill()
        with self._lock:
            self._last_end_time = time.time()

    def _wait_for_end(self):
        with self._lock:
            proc = self._proc
        if not proc:
            return
        proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._last_end_time = time.time()
        if self._on_play_end:
            self._on_play_end()
