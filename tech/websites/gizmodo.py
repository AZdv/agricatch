from agricatch.website import Website

DC = "http://purl.org/dc/elements/1.1/"


class Gizmodo(Website):
    # The original feeds.gawker.com address died with Gawker Media in 2016.
    namespaces = {"dc": DC}
    url_info = {"url": "https://gizmodo.com/feed"}
    structure = {
        "child_xpath": "//channel/item",
        "fields": {
            "name": {"xpath": "title/text()"},
            "description": {"xpath": "description/text()", "required": False},
            "link": {"xpath": "link/text()"},
            "author": {
                "type": "table",
                "model": "Author",
                "lookup": ["name"],
                "required": False,
                "fields": {"name": {"xpath": "dc:creator/text()"}},
            },
            "time": {"type": "time", "xpath": "pubDate/text()"},
        },
    }
