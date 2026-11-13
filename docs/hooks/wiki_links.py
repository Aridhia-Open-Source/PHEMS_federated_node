"""MkDocs hooks that let the pages in docs/versions/2.x/docs serve both the GitHub wiki and this site.

The GitHub wiki wants extensionless links ([x](./Deploy-Core#anchor)) and a page called
Home. MkDocs wants relative .md links and an index page. Instead of changing the pages,
rewrite them while the site is built, so the wiki sync keeps copying the pages unchanged.
"""

import re

# [text](./Page) or [text](./Page#anchor); external links and bare anchors never match
WIKI_LINK = re.compile(r"\]\(\./(?P<page>[^)#\s]+)(?P<anchor>#[^)\s]*)?\)")


def on_files(files, config):
    # Home.md is the wiki's front page; make it this site's front page as well.
    files.get_file_from_path("Home.md").dest_uri = "index.html"
    return files


def on_page_markdown(markdown, page, config, files):
    def to_md_link(match):
        target = f"{match['page']}.md"
        if files.get_file_from_path(target) is None:
            return match[0]
        return f"]({target}{match['anchor'] or ''})"

    return WIKI_LINK.sub(to_md_link, markdown)
