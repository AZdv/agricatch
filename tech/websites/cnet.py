from agricatch.website import Website

ATOM = "http://www.w3.org/2005/Atom"
MEDIA = "http://search.yahoo.com/mrss/"


class Cnet(Website):
    # CNET moved from RSS to Atom, so entries are namespaced and the link is an
    # attribute rather than element text.
    namespaces = {"atom": ATOM, "media": MEDIA}
    url_info = {"url": "https://www.cnet.com/rss/news/"}
    structure = {
        "child_xpath": "//atom:entry",
        "fields": {
            "name": {"xpath": "atom:title/text()"},
            "description": {"xpath": "atom:summary/text()", "required": False},
            "link": {"xpath": 'atom:link[@rel="alternate"]/@href'},
            "author": {"xpath": "atom:author/atom:name/text()", "required": False},
            "image": {"xpath": "media:content/@url", "required": False},
            # published can be years old on evergreen articles; updated is when
            # the entry actually surfaced in the feed.
            "time": {"type": "time", "xpath": "atom:updated/text()"},
        },
    }
