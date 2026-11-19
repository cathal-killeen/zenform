"""Shared test fixtures: a small synthetic session, never a real one."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from zenform import model  # noqa: E402

WS = "{ws-1}"


def tab(url, *, label=None, essential=False, group=None, pinned=True, current=None):
    t = model.new_pin(label or url, url, essential=essential, group=group, workspace=WS)
    t["pinned"] = pinned
    if current:  # the pin has been navigated away from its home page
        t["entries"] = [{"url": url}, {"url": current}]
        t["index"] = 2
    return t


def session():
    ph = model.new_placeholder("g1", WS)
    return {
        "spaces": [{"uuid": WS, "name": "Work"}],
        "tabs": [
            tab("https://mail/", label="Inbox - long title", essential=True, current="https://mail/other"),
            ph,
            tab("https://wiki/", label="Wiki page", group="g1", current="https://wiki/deep"),
            tab("https://old/", label="Old pin"),
            {"entries": [{"url": "https://open/"}], "pinned": False, "index": 1},
        ],
        "folders": [
            {
                "id": "g1",
                "name": "Docs",
                "collapsed": True,
                "emptyTabIds": [ph["zenSyncId"]],
                "prevSiblingInfo": None,
                "workspaceId": WS,
            }
        ],
        "groups": [{"id": "g1", "name": "Docs", "collapsed": True}],
    }


SPEC = {
    "workspace": "Work",
    "essentials": [{"label": "Mail", "url": "https://mail/"}],
    "folders": [
        {"name": "Docs", "pins": [{"label": "Wiki", "url": "https://wiki/"}]},
        {"name": "New", "pins": [{"label": "Fresh", "url": "https://fresh/"}]},
    ],
}
