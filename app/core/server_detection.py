"""Identify supported servers from authenticated API responses, never ports."""
import xml.etree.ElementTree as ET
from core.http_security import server_http_session
from core.jellyfin_auth import jellyfin_headers


class ServerDetectionError(RuntimeError):
    pass


def detect_server(url, token):
    token = str(token or "").strip()
    if not token:
        raise ServerDetectionError("server_connection_rejected")
    http = server_http_session({"url":url})
    try:
        probes = [
            ("arr", "/api/v3/system/status", {"X-Api-Key":token,"Accept":"application/json"}),
            ("jellyfin", "/System/Info", jellyfin_headers(token)),
            ("plex", "/", {"X-Plex-Token":token,"Accept":"application/xml"}),
        ]
        for provider,path,headers in probes:
            try:
                response=http.get(url.rstrip("/")+path,headers=headers,timeout=4,allow_redirects=False)
                if response.status_code != 200:
                    continue
                if provider == "plex":
                    data=ET.fromstring(response.content)
                    if data.tag != "MediaContainer" or not data.get("machineIdentifier") or not data.get("version"):
                        continue
                    access=http.get(url.rstrip("/")+"/library/sections",headers=headers,
                                    timeout=4,allow_redirects=False)
                    if access.status_code != 200 or ET.fromstring(access.content).tag != "MediaContainer":
                        continue
                    return {"type":"plex","name":data.get("friendlyName") or "Plex",
                            "identifier":data.get("machineIdentifier"),"version":data.get("version")}
                data=response.json()
                if not isinstance(data,dict):
                    continue
                if provider == "arr":
                    app=str(data.get("appName") or "").lower()
                    if app not in ("sonarr","radarr") or not data.get("version"):
                        continue
                    return {"type":app,"name":data.get("instanceName") or app.capitalize(),
                            "identifier":None,"version":str(data["version"])}
                if (str(data.get("ProductName") or "").lower() != "jellyfin"
                        or not data.get("Id") or not data.get("Version")):
                    continue
                return {"type":"jellyfin","name":data.get("ServerName") or "Jellyfin",
                        "identifier":str(data["Id"]),"version":str(data["Version"])}
            except Exception:
                continue
        raise ServerDetectionError("server_connection_rejected")
    except ServerDetectionError:
        raise
    except Exception:
        raise ServerDetectionError("server_connection_rejected") from None
    finally:
        http.close()
