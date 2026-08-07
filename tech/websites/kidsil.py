from __future__ import annotations

from urllib.parse import urljoin

from agricatch.website import Node, Record, Website

BASE_URL = "https://www.kidsil.net/"


class Kidsil(Website):
    """A blog rather than a feed, so this one is scraped as HTML.

    The listing only carries a ~160 character excerpt while the post itself runs
    to a couple of thousand, so the fields are read off each post's own page via
    ``object_url``. That costs one request per post, which is what ``max_pages``
    is bounding: an index page plus its five posts, twice over.
    """

    parser = "html"
    max_pages = 12

    url_info = {"url": BASE_URL}
    structure = {
        "child_xpath": '//ul[contains(@class,"post-list")]/li',
        "object_url": "h2/a/@href",
        "pagination": '//a[contains(@href,"/page/")]',
        "fields": {
            "name": {"xpath": '//article//h1[contains(@class,"post-title")]'},
            "link": {"xpath": '//link[@rel="canonical"]/@href'},
            "description": {"xpath": '//article//div[contains(@class,"post-content")]'},
            "image": {
                "xpath": '//article//div[contains(@class,"post-image-wrapper")]//img/@src',
                "required": False,
            },
            "time": {
                "type": "time",
                "xpath": '//article//div[contains(@class,"post-meta")]/a',
            },
        },
    }

    def hydrate(self, record: Record, node: Node) -> Record:
        # Images are served protocol-relative (//media.kidsil.net/...).
        if record.get("image"):
            record["image"] = urljoin(BASE_URL, record["image"])
        return record
