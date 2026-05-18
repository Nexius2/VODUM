# app/utils/platform_detection.py

from pathlib import Path
import platform
import os
import subprocess


def detect_platform():
    """
    Detect runtime environment and OS information
    for Vodum telemetry/debugging.
    """

    result = {
        "platform": "unknown",
        "os": "unknown",
        "container": False,
        "virtualized": False,
    }

    try:

        system = platform.system().lower()

        # =========================================================
        # WINDOWS
        # =========================================================

        if system == "windows":

            result["platform"] = "windows"

            version = platform.version()
            release = platform.release()

            result["os"] = f"Windows {release} ({version})"

            return result

        # =========================================================
        # LINUX
        # =========================================================

        if system == "linux":

            result["platform"] = "linux"

            # -----------------------------------------------------
            # DOCKER / CONTAINER
            # -----------------------------------------------------

            if Path("/.dockerenv").exists():

                result["container"] = True
                result["platform"] = "docker"

            elif Path("/run/.containerenv").exists():

                result["container"] = True
                result["platform"] = "container"

            # -----------------------------------------------------
            # UNRAID
            # -----------------------------------------------------

            if Path("/etc/unraid-version").exists():

                try:

                    unraid_version = (
                        Path("/etc/unraid-version")
                        .read_text()
                        .strip()
                    )

                    result["platform"] = "unraid"

                    if result["container"]:
                        result["platform"] = "docker-unraid"

                    result["os"] = unraid_version

                    return result

                except Exception:
                    pass

            # -----------------------------------------------------
            # LXC
            # -----------------------------------------------------

            try:

                cgroup = Path("/proc/1/cgroup").read_text()

                if "lxc" in cgroup:

                    result["container"] = True

                    if result["platform"] == "linux":
                        result["platform"] = "lxc"

            except Exception:
                pass

            # -----------------------------------------------------
            # KUBERNETES
            # -----------------------------------------------------

            if os.environ.get("KUBERNETES_SERVICE_HOST"):

                result["container"] = True
                result["platform"] = "kubernetes"

            # -----------------------------------------------------
            # VM DETECTION
            # -----------------------------------------------------

            try:

                output = subprocess.check_output(
                    ["systemd-detect-virt"],
                    stderr=subprocess.DEVNULL,
                    text=True
                ).strip()

                if output and output != "none":

                    result["virtualized"] = True

                    if not result["container"]:
                        result["platform"] = f"vm-{output}"

            except Exception:
                pass

            # -----------------------------------------------------
            # OS RELEASE
            # -----------------------------------------------------

            os_release = {}

            if Path("/etc/os-release").exists():

                try:

                    for line in Path("/etc/os-release").read_text().splitlines():

                        if "=" not in line:
                            continue

                        key, value = line.split("=", 1)

                        os_release[key] = value.strip('"')

                except Exception:
                    pass

            pretty_name = os_release.get("PRETTY_NAME")

            if pretty_name:

                result["os"] = pretty_name

            else:

                distro = platform.platform()

                result["os"] = distro

            return result

        # =========================================================
        # MACOS
        # =========================================================

        if system == "darwin":

            result["platform"] = "macos"

            mac_ver = platform.mac_ver()[0]

            result["os"] = f"macOS {mac_ver}"

            return result

        # =========================================================
        # FALLBACK
        # =========================================================

        result["os"] = platform.platform()

    except Exception as e:

        result["error"] = str(e)

    return result


# =============================================================
# TEST
# =============================================================

if __name__ == "__main__":

    import json

    print(
        json.dumps(
            detect_platform(),
            indent=4
        )
    )