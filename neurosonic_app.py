"""Start the NeuroSonic app (local web server + WOAD detector).

  python neurosonic_app.py                          -> http://127.0.0.1:8765  (laptop browser)
  python neurosonic_app.py --host 0.0.0.0 --https   -> https://<laptop-ip>:8765 for a phone on the same Wi-Fi
                                                       + http://<laptop-ip>:8766  one-time phone setup page
Phones only allow camera and GPS on HTTPS pages (or localhost). --https creates a local certificate authority
and a server certificate in data/tls/ (openssl command; see neurosonic/tls.py). Install the CA once on the
phone from the setup page; browser security is not disabled. On Windows, the phone can only connect if the
firewall allows it - the start-up check prints the exact commands (docs/NEUROSONIC_APP.md, "Phone access").
Assistive prototype only: not a replacement for a cane, guide dog or human assistance.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from neurosonic.netcheck import print_report, windows_report  # noqa: E402
from neurosonic.server import make_server, make_setup_server, serve_in_thread  # noqa: E402
from neurosonic.service import DetectionService  # noqa: E402
from neurosonic.store import Store  # noqa: E402
from neurosonic.tls import TLSSetupError, ensure_certificates, lan_ips, server_ssl_context  # noqa: E402
from neurosonic.tts import DEFAULT_VOICE, PiperTTS  # noqa: E402
from woad.model_loader import DEFAULT_WEIGHTS  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow phones on the local network")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--https", action="store_true", help="serve over HTTPS with a local CA-signed certificate")
    ap.add_argument("--setup-port", type=int, default=None, help="phone setup page port (default: --port + 1)")
    ap.add_argument("--no-network-check", action="store_true", help="skip the Windows firewall/network check")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "neurosonic.sqlite3")
    ap.add_argument("--voice-model", type=Path, default=DEFAULT_VOICE, help="Piper .onnx voice (local neural TTS)")
    ap.add_argument("--map", type=Path, default=ROOT / "maps" / "vellore", help="offline map package folder")
    ap.add_argument("--asr-model", type=Path, default=ROOT / "models" / "asr" / "vosk-model-small-en-in-0.4",
                    help="Vosk model for offline voice commands")
    ap.add_argument("--rgb-weights", type=Path,
                    default=ROOT / "models" / "rgb" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth",
                    help="COCO detector weights for live camera awareness")
    ap.add_argument("--detector", default=None, choices=["auto", "rfdetr", "ssdlite"],
                    help="camera detector (default: $NEUROSONIC_DETECTOR or auto). auto = RF-DETR Nano on the NVIDIA "
                         "GPU when available (run from .venv-gpu), otherwise SSDLite on the CPU")
    ap.add_argument("--no-events", action="store_true", help="disable the entering / crossing event messages")
    ap.add_argument("--vision-provider", default=None, choices=["gemini", "mock", "off"],
                    help="online scene description provider (default: $NEUROSONIC_VISION_PROVIDER or gemini). "
                         "The Gemini key is read only on this laptop from GEMINI_API_KEY")
    ap.add_argument("--vision-model", default=None, help="cloud model (default: $NEUROSONIC_VISION_MODEL or gemini-3.8-flash)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)
    lan = a.host != "127.0.0.1"
    setup_port = a.setup_port or a.port + 1

    ctx = tls = None
    if a.https:
        try:
            tls = ensure_certificates(ROOT / "data" / "tls")
        except TLSSetupError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        ctx = server_ssl_context(tls)

    a.db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(a.db)
    print("Loading WOAD model ...")
    service = DetectionService(store, a.weights, a.device)
    tts = PiperTTS(a.voice_model, cache_dir=ROOT / "data" / "tts_cache")
    if tts.warm_up():
        i = tts.info()
        print(f"Voice: Piper {i['engine_version']} - {i['voice']} ({i['language']}), loaded in {i.get('load_ms')} ms")
    else:
        print(f"Voice: local neural voice UNAVAILABLE ({tts.error}); phones will use their browser voice")
    offline_map = None
    if (a.map / "manifest.json").exists():
        from neurosonic.maps import OfflineMap
        offline_map = OfflineMap(a.map)
        mi = offline_map.info()
        b = mi["bbox"]
        print(f"Offline map: {mi['region']} ({b['south']},{b['west']} - {b['north']},{b['east']}), "
              f"{mi['graph_nodes']} path nodes, {mi['places']} places, OSM data {mi['osm_timestamp']}")
    else:
        print(f"Offline map: none found at {a.map}")
    from neurosonic.voicecmd import VoiceCommands
    voicecmd = VoiceCommands(a.asr_model, offline_map=offline_map)
    print("Voice commands: offline Vosk " + (f"{voicecmd.model_dir.name} ready" if voicecmd.warm_up()
                                             else f"UNAVAILABLE ({voicecmd.error})"))
    from neurosonic.awareness import RGBAwareness
    import os
    awareness = RGBAwareness(a.rgb_weights, detector=a.detector or os.environ.get("NEUROSONIC_DETECTOR") or "auto",
                             events=not a.no_events)
    if awareness.warm_up():
        ai = awareness.info()
        d = ai["detector"]
        print(f"Camera awareness: {ai['model']} ready ({d['device']}; frame interval {ai['recommended_frame_ms']} ms; "
              f"events: {ai['events']})" + (f"\n  fallback: {d['fallback_reason']}" if d["fallback_reason"] else ""))
    else:
        print(f"Camera awareness: UNAVAILABLE ({awareness.error})")
    from neurosonic.vision import SceneAssistant
    from neurosonic.vision.gemini import make_provider
    provider = make_provider(a.vision_provider, a.vision_model)
    vision = SceneAssistant(provider, enabled=provider is not None)
    vi = vision.info()
    if provider is None:
        print("Online scene description: OFF (--vision-provider off)")
    elif vi["configured"]:
        print(f"Online scene description: {vi['provider']} / {vi['model']} configured (needs internet; opt-in on the "
              f"phone; {vi['attempt_timeout_s']:g} s per attempt, {vi['budget_s']:g} s budget, at most "
              f"{vi['max_retries']} retry for a quick 503)")
    else:
        print(f"Online scene description: NOT AVAILABLE ({vi['problem']}); local guidance is unaffected")
    try:
        httpd = make_server(service, store, a.host, a.port, quiet=not a.verbose, ssl_context=ctx, tts=tts,
                            offline_map=offline_map, voicecmd=voicecmd, awareness=awareness, vision=vision)
    except OSError as e:
        print(f"ERROR: cannot listen on {a.host}:{a.port}: {e} (is the app already running?)", file=sys.stderr)
        store.close()
        return 2
    setup = None
    scheme = "https" if ctx else "http"
    ips = lan_ips() if lan else []
    app_url = f"{scheme}://{ips[0] if ips else '127.0.0.1'}:{a.port}"
    if ctx and lan:
        setup = make_setup_server(tls["ca_cert"], app_url, tls["ca_fingerprint"], a.host, setup_port,
                                  quiet=not a.verbose)
        serve_in_thread(setup)

    print(f"NeuroSonic running: {scheme}://127.0.0.1:{a.port}   (listening on {a.host}:{a.port})")
    if lan:
        for ip in ips or ["<no LAN address found>"]:
            print(f"  phone / other devices:  {scheme}://{ip}:{a.port}")
        if setup:
            print(f"  one-time phone setup (open in Safari on iPhone):  http://{ips[0] if ips else '<laptop-ip>'}:{setup_port}")
            print(f"  NeuroSonic Local CA SHA-256: {tls['ca_fingerprint']}")
        elif not ctx:
            print("  note: over plain HTTP, phones block camera and GPS; use --https for those features.")
        print("  WARNING: devices on this network can reach the app; use only on a trusted network.")
        if not a.no_network_check:
            rep = windows_report([a.port] + ([setup_port] if setup else []))
            print_report(rep)
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop_replay()
        httpd.server_close()
        if setup:
            setup.shutdown()
            setup.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
