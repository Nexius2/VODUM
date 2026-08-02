import xml.etree.ElementTree as ET


def plex_title_to_id_map(account, machine_id: str) -> dict:
    response = account.query(f"https://plex.tv/api/servers/{machine_id}", account._session.get)
    if hasattr(response, "findall"):
        root = response
    else:
        try:
            root = ET.fromstring(response)
        except Exception as exc:
            raise RuntimeError("Unable to parse Plex server sections XML") from exc
    return {
        section.attrib["title"]: section.attrib["id"]
        for section in root.findall(".//Section")
        if section.attrib.get("title") and section.attrib.get("id")
    }


def get_shared_servers_for_machine(account, machine_id: str) -> list[dict]:
    response = account.query(
        f"https://plex.tv/api/servers/{machine_id}/shared_servers",
        account._session.get,
    )
    if isinstance(response, ET.Element):
        root = response
    else:
        if hasattr(response, "text") and isinstance(response.text, str):
            xml_text = response.text
        elif isinstance(response, (str, bytes)):
            xml_text = response.decode() if isinstance(response, bytes) else response
        else:
            try:
                xml_text = ET.tostring(response).decode("utf-8")
            except Exception:
                xml_text = str(response)
        root = ET.fromstring(xml_text)

    output = []
    for shared in root.findall(".//SharedServer"):
        section_ids = []
        raw_ids = (
            shared.attrib.get("librarySectionIDs")
            or shared.attrib.get("librarySectionIds")
            or shared.attrib.get("library_section_ids")
            or ""
        )
        for part in str(raw_ids).replace(";", ",").split(","):
            if part.strip().isdigit():
                section_ids.append(int(part.strip()))
        for child in list(shared):
            child_id = (
                child.attrib.get("id") or child.attrib.get("key")
                or child.attrib.get("librarySectionID")
                or child.attrib.get("librarySectionId")
            )
            if child_id and str(child_id).isdigit():
                section_ids.append(int(child_id))
        output.append({
            "id": shared.attrib.get("id"),
            "username": shared.attrib.get("username"),
            "email": shared.attrib.get("email"),
            "userID": shared.attrib.get("userID") or shared.attrib.get("userId"),
            "invitedId": (
                shared.attrib.get("invitedId") or shared.attrib.get("invitedID")
                or shared.attrib.get("invited_id")
            ),
            "section_ids": sorted(set(section_ids)),
        })
    return output
