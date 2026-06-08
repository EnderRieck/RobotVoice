#!/usr/bin/env python
# coding: utf-8
"""Standalone microphone capture meter (no network).

Records a couple of seconds from each candidate input device / sample-rate and
prints the RMS and peak amplitude so you can find a device that actually picks
up your voice. KEEP TALKING the whole time it runs.

Run:
    pixi run python local_tests/mic_check.py
    pixi run python local_tests/mic_check.py --devices 3,20,11 --rates 16000,48000
"""

from __future__ import print_function

import argparse
import audioop
import time

import sounddevice as sd


def measure(device, samplerate, seconds):
    blocksize = int(samplerate * 0.1)
    rms_peak = 0
    amp_peak = 0
    try:
        with sd.RawInputStream(
            samplerate=samplerate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=device,
        ) as stream:
            start = time.time()
            while time.time() - start < seconds:
                data, _ = stream.read(blocksize)
                data = bytes(data)
                rms_peak = max(rms_peak, audioop.rms(data, 2))
                amp_peak = max(amp_peak, audioop.max(data, 2))
    except Exception as exc:
        return "ERROR: {}".format(exc)
    verdict = "LIVE" if amp_peak > 500 else "silent"
    return "rms_peak={:>6} amp_peak={:>6}  [{}]".format(rms_peak, amp_peak, verdict)


def parse_args():
    parser = argparse.ArgumentParser(description="Microphone capture meter.")
    parser.add_argument("--devices", default="default,3,20,11",
                        help="comma list of device indexes (or 'default')")
    parser.add_argument("--rates", default="16000,48000,24000",
                        help="comma list of sample rates to try")
    parser.add_argument("--seconds", type=float, default=2.0)
    return parser.parse_args()


def main():
    args = parse_args()
    devices = [None if d.strip() == "default" else int(d) for d in args.devices.split(",") if d.strip()]
    rates = [int(r) for r in args.rates.split(",") if r.strip()]
    print("KEEP TALKING for the whole test...\n")
    for device in devices:
        for rate in rates:
            label = "default" if device is None else device
            print("device={:>7} rate={:>6}: {}".format(label, rate, measure(device, rate, args.seconds)))


if __name__ == "__main__":
    main()
