"""Recognize a focused Disney+ profile from a fresh UI dump; no device operations."""
from xml.etree import ElementTree


def is_focused_profile(xml, profile_name, package="com.disney.disneyplus"):
    if (not isinstance(xml, str) or len(xml.encode("utf-8")) > 65536
            or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper()):
        return False
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, ValueError):
        return False
    nodes = list(root.iter("node"))
    if root.tag != "hierarchy" or not nodes or any(n.get("package") != package for n in nodes):
        return False
    pickers = [n for n in nodes if n.get("resource-id") == package + ":id/profilesContent"]
    if len(pickers) != 1:
        return False
    picker = pickers[0]
    if not any(n.get("text") == "Who's watching?" for n in picker.iter("node")):
        return False
    targets = [n for n in picker.iter("node")
               if n.get("content-desc") == f"Access {profile_name}'s profile"]
    focused = [n for n in nodes if n.get("focused") == "true"]
    if len(targets) != 1 or len(focused) != 1 or targets[0].get("enabled") != "true":
        return False
    # The supplied Fire TV dump exposes the profile label directly under its card.
    parents = {child: parent for parent in root.iter() for child in parent}
    card = parents.get(targets[0])
    return (card is focused[0] and all(card.get(flag) == "true"
                                     for flag in ("enabled", "clickable", "focusable")))
