from agricatch.website import Website

DC = "http://purl.org/dc/elements/1.1/"


class Techcrunch(Website):
    namespaces = {"dc": DC}
    url_info = {"url": "https://techcrunch.com/feed/"}
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
