from abc import ABC, abstractmethod
from datetime import datetime, date, timezone
from typing import Any, Iterable, Tuple


def _normalize_dt(dt: datetime | date | str | None) -> float:
    if not dt:
        return 0

    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.strip())
    if isinstance(dt, date):
        dt = datetime.combine(dt, datetime.min.time())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.timestamp()


class PagesSorter(ABC):
    _default_published = datetime.fromtimestamp(0)

    def __init__(self, pages: Iterable[dict]):
        self.pages = pages

    @abstractmethod
    def __call__(self, page: dict) -> Any:
        raise NotImplemented()


class PagesSortByTime(PagesSorter):
    def __call__(self, page: dict) -> float:
        return _normalize_dt(page.get("published", self._default_published))


class PagesSortByFolderAndTime(PagesSorter):
    def __call__(self, page: dict) -> Tuple:
        return (
            page.get("folder"),
            _normalize_dt(
                date.today() - page.get("published", self._default_published)
            ),
        )


class PagesSortByTimeGroupedByFolder(PagesSorter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        st = {}
        for page in self.pages:
            folder = page.get("folder", "")
            published = _normalize_dt(page.get("published", self._default_published))
            st[folder] = st.get(folder, published)
            st[folder] = max(st[folder], published)

        self._max_date_by_folder = st

    def __call__(self, page: dict) -> Tuple:
        return (
            self._max_date_by_folder[page.get("folder", "")],
            _normalize_dt(page.get("published", self._default_published)),
        )
