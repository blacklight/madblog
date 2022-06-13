from abc import ABC, abstractmethod
from datetime import datetime, date
from typing import Any, Iterable, Tuple


class PagesSorter(ABC):
    _default_published = date.fromtimestamp(0)

    def __init__(self, pages: Iterable[dict]):
        self.pages = pages

    @abstractmethod
    def __call__(self, page: dict) -> Any:
        raise NotImplemented()


class PagesSortByTime(PagesSorter):
    def __call__(self, page: dict) -> datetime:
        return page.get('published', self._default_published)


class PagesSortByFolderAndTime(PagesSorter):
    def __call__(self, page: dict) -> Tuple:
        return (
            page.get('folder'),
            date.today() - page.get(
                'published', self._default_published
            )
        )


class PagesSortByTimeGroupedByFolder(PagesSorter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        st = {}
        for page in self.pages:
            folder = page.get('folder', '')
            published = page.get('published', self._default_published)
            st[folder] = st.get(folder, published)
            st[folder] = max(st[folder], published)

        self._max_date_by_folder = st

    def __call__(self, page: dict) -> Tuple:
        return (
            self._max_date_by_folder[page.get('folder', '')],
            page.get('published', self._default_published)
        )
