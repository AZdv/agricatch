from urllib.parse import urljoin

from agricatch.website import Website

BASE_URL = "https://www.kidsil.net/"


class Kidsil(Website):
    # A blog rather than a feed, so this one is scraped as HTML.
    parser = "html"
    url_info = {"url": BASE_URL}
    structure = {
        "child_xpath": '//ul[contains(@class,"post-list")]/li',
        "fields": {
            "name": {"xpath": "h2/a"},
            "link": {"xpath": "h2/a/@href"},
            "description": {
                "xpath": 'div[contains(@class,"post-content")]',
                "required": False,
            },
            "image": {
                "xpath": 'div[contains(@class,"post-image-wrapper")]//img/@src',
                "required": False,
            },
            "time": {"type": "time", "xpath": 'div[contains(@class,"post-meta")]/a'},
        },
    }

    def hydrate(self, record, node):
        # Links are site-relative and images are protocol-relative (//media...).
        for key in ("link", "image"):
            if record.get(key):
                record[key] = urljoin(BASE_URL, record[key])
        return record
