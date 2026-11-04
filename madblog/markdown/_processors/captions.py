"""
Markdown extension: wraps standalone images that have a meaningful
``alt`` text in ``<figure>`` + ``<figcaption>`` elements, so the alt
text is also displayed as a caption under the image.

Only images that are the sole content of a paragraph are wrapped —
inline images are left untouched. An ``alt`` of ``.`` (the placeholder
used for decorative images) counts as no alt text, same as an empty
one.
"""

import xml.etree.ElementTree as ElementTree

import markdown
from markdown.treeprocessors import Treeprocessor


def meaningful_alt(alt: str | None) -> str:
    """
    Return the stripped *alt* text if it is meaningful, otherwise ``""``.

    ``.`` is treated as "decorative image" — the placeholder used by
    the templates for images without alt text.
    """
    if not alt:
        return ""
    alt = alt.strip()
    return "" if alt == "." else alt


class ImageCaptionsTreeprocessor(  # pylint: disable=too-few-public-methods
    Treeprocessor
):
    """Wrap standalone ``<img>`` elements with alt text in ``<figure>``."""

    def run(self, root):
        parent_map = {child: parent for parent in root.iter() for child in parent}

        for elem, parent in parent_map.items():
            if elem.tag != "p" or len(elem) != 1:
                continue

            img = elem[0]
            if img.tag != "img":
                continue

            if (elem.text or "").strip() or (img.tail or "").strip():
                continue

            alt = meaningful_alt(img.get("alt"))
            if not alt:
                continue

            figure = ElementTree.Element("figure")
            figure.set("class", "image-figure")
            figure.tail = elem.tail

            img.tail = None
            figure.append(img)

            figcaption = ElementTree.SubElement(figure, "figcaption")
            figcaption.set("class", "image-caption")
            figcaption.text = alt

            parent.insert(list(parent).index(elem), figure)
            parent.remove(elem)

        return root


class MarkdownImageCaptions(markdown.Extension):
    """Wrapper that registers :class:`ImageCaptionsTreeprocessor`."""

    def extendMarkdown(self, md):
        # Priority 15 — after ``inline`` (20) has produced the <img>
        # elements, before ``prettify`` (10) and ``attr_list`` (8).
        md.treeprocessors.register(
            ImageCaptionsTreeprocessor(md),
            "image_captions",
            15,
        )
