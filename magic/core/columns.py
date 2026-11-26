"""欄位名稱搜尋：忽略大小寫、空白與符號；完全相同優先，其次是「包含」。

和 yeep_lab.io_qd.find_col 不同：好幾個欄位都符合時不會默默拿第一個，
會回傳所有候選，讓呼叫的地方提醒使用者（例如 Bridge 1 / 2 / 3 Resistance）。
"""
from __future__ import annotations


def norm(s) -> str:
    return "".join(ch.lower() for ch in str(s) if ch.isalnum())


def candidates(columns, name):
    """回傳 (完全相同的欄位, 包含關係的欄位)。"""
    target = norm(name)
    cols = list(columns)
    exact = [c for c in cols if norm(c) == target]
    partial = [c for c in cols if target and target in norm(c) and c not in exact]
    return exact, partial


class ColumnNotFound(KeyError):
    def __init__(self, name, columns):
        self.name = name
        self.columns = list(columns)
        super().__init__(f"找不到欄位「{name}」；可用的欄位：{', '.join(map(str, self.columns))}")

    def __str__(self):
        return self.args[0]


def find_col(columns, name, warn=None, required=False):
    """模糊尋找欄位。找不到回傳 None（required=True 時丟出 ColumnNotFound）。

    有好幾個欄位都包含 name 時，用第一個並呼叫 warn("…")。"""
    if hasattr(columns, "columns"):
        columns = columns.columns
    if name is None or str(name).strip() == "":
        if required:
            raise ColumnNotFound(name, columns)
        return None
    if name in list(columns):
        return name
    exact, partial = candidates(columns, name)
    if exact:
        return exact[0]
    if partial:
        if len(partial) > 1 and warn:
            warn(f"「{name}」符合好幾個欄位，使用「{partial[0]}」；其他：{'、'.join(map(str, partial[1:]))}")
        return partial[0]
    if required:
        raise ColumnNotFound(name, columns)
    return None


def resolve(columns, choice, warn=None, required=True):
    """欄位可以用名稱（可模糊）、或欄位編號（整數 / 數字字串）指定。"""
    if hasattr(columns, "columns"):
        columns = columns.columns
    cols = list(columns)
    if isinstance(choice, int) and not isinstance(choice, bool):
        if 0 <= choice < len(cols):
            return cols[choice]
        raise ColumnNotFound(choice, cols)
    s = str(choice).strip() if choice is not None else ""
    if s.isdigit() and s not in cols:
        i = int(s)
        if 0 <= i < len(cols):
            return cols[i]
    return find_col(cols, s, warn=warn, required=required)


def first_present(columns, names, warn=None):
    """依序試 names，回傳第一個找得到的欄位（都沒有回傳 None）。"""
    for n in names:
        c = find_col(columns, n, warn=warn)
        if c is not None:
            return c
    return None
