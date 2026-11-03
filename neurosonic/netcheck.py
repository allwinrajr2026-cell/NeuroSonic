"""Read-only check of the Windows settings that decide whether a phone can reach the app on the LAN.

Diagnosed 2026-11-02: the laptop's Wi-Fi was classified as a *Public* network, Windows Defender Firewall was on
for all profiles, and no inbound rule allowed Python or the app's ports. Windows then silently drops the phone's
connection attempts, so the phone browser just spins (HTTP and HTTPS alike), while the laptop itself still
works (connections to its own address are not filtered).

This module only reads settings and prints the exact commands; it never changes the firewall (that needs an
administrator and is the user's decision).
"""
import json
import subprocess
import sys

RULE_NAME = "NeuroSonic LAN"


def _ps(command, timeout=15):
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip()


def windows_report(ports):
    """Returns {"profiles": [...], "rule_present": bool|None, "warnings": [...], "fix_commands": [...]}."""
    rep = {"profiles": [], "rule_present": None, "warnings": [], "fix_commands": []}
    if sys.platform != "win32":
        return rep
    try:
        rc, out = _ps("Get-NetConnectionProfile | Select-Object InterfaceAlias,NetworkCategory | ConvertTo-Json -Compress")
        if rc == 0 and out:
            data = json.loads(out)
            data = data if isinstance(data, list) else [data]
            cat = {0: "Public", 1: "Private", 2: "DomainAuthenticated"}
            rep["profiles"] = [{"interface": d.get("InterfaceAlias"),
                                "category": cat.get(d.get("NetworkCategory"), d.get("NetworkCategory"))} for d in data]
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"],
                           capture_output=True, text=True, timeout=15)
        rep["rule_present"] = r.returncode == 0 and "Rule Name" in r.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        rep["warnings"].append("Could not read the Windows network/firewall settings.")
        return rep

    port_list = ",".join(str(p) for p in ports)
    public = [p["interface"] for p in rep["profiles"] if p["category"] == "Public"]
    if public:
        rep["warnings"].append(f"Network {', '.join(public)} is set to 'Public': Windows blocks incoming connections "
                               "from other devices on Public networks.")
        for iface in public:
            rep["fix_commands"].append(f'Set-NetConnectionProfile -InterfaceAlias "{iface}" -NetworkCategory Private')
    if not rep["rule_present"]:
        rep["warnings"].append(f"No Windows Firewall rule '{RULE_NAME}' allows TCP {port_list} from the local network, "
                               "so the phone's connections are dropped.")
        rep["fix_commands"].append(
            f'New-NetFirewallRule -DisplayName "{RULE_NAME}" -Direction Inbound -Action Allow -Protocol TCP '
            f'-LocalPort {port_list} -RemoteAddress LocalSubnet -Profile Private')
    return rep


def print_report(rep):
    for w in rep["warnings"]:
        print(f"  ! {w}")
    if rep["fix_commands"]:
        print("  To allow your phone (home/trusted Wi-Fi only), run once in PowerShell *as Administrator*:")
        for c in rep["fix_commands"]:
            print(f"      {c}")
        print("  (Undo: Remove-NetFirewallRule -DisplayName \"NeuroSonic LAN\"; "
              "Set-NetConnectionProfile -InterfaceAlias <name> -NetworkCategory Public)")
