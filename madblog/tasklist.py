import re
from xml.etree import ElementTree

import markdown


_TASK_ITEM_RE = re.compile(r"^\s*\[(?P<state>[ xX])\]\s+")


def _apply_task_marker(parent: ElementTree.Element) -> bool:
    """Apply task list marker transformation to a single element.

    Returns True if a marker was found and replaced.
    """

    text = parent.text or ""
    m = _TASK_ITEM_RE.match(text)
    if not m:
        return False

    state = m.group("state")
    checkbox = ElementTree.Element(
        "input", {"type": "checkbox", "disabled": "disabled"}
    )
    if state.lower() == "x":
        checkbox.set("checked", "checked")

    remaining = text[m.end() :]
    if remaining and not remaining.startswith(" "):
        remaining = " " + remaining

    parent.text = ""
    checkbox.tail = remaining
    parent.insert(0, checkbox)
    return True


def _add_task_list_class(li: ElementTree.Element):
    classes = (li.get("class") or "").split()
    if "task-list-item" not in classes:
        classes.append("task-list-item")
    li.set("class", " ".join(c for c in classes if c))


class TaskListTreeprocessor(markdown.treeprocessors.Treeprocessor):
    def run(self, root: ElementTree.Element):
        for li in root.iter("li"):
            if _apply_task_marker(li):
                _add_task_list_class(li)
                continue

            # If the list item starts with a paragraph, the marker may be in there.
            if len(li) > 0 and li[0].tag == "p":
                if _apply_task_marker(li[0]):
                    _add_task_list_class(li)


class MarkdownTaskList(markdown.Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(TaskListTreeprocessor(md), "task_list", 15)
