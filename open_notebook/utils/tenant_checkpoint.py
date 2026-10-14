"""LangGraph checkpoint store that keeps every user's chat threads apart.

Chat history checkpoints live in one SQLite file. Thread ids are namespaced
with the active tenant's database name, so a thread id from one user can
never load or overwrite another user's conversation.
"""

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver

from open_notebook import tenancy


def _scoped(config: Optional[RunnableConfig]) -> Optional[RunnableConfig]:
    if not config:
        return config
    conf = dict(config.get("configurable") or {})
    thread = conf.get("thread_id")
    if thread is None:
        return config
    prefix = (tenancy.current_tenant_db() or "core") + "::"
    if not str(thread).startswith(prefix):
        conf["thread_id"] = prefix + str(thread)
    return {**config, "configurable": conf}


class TenantSqliteSaver(SqliteSaver):
    def get_tuple(self, config: RunnableConfig):  # type: ignore[override]
        return super().get_tuple(_scoped(config))  # type: ignore[arg-type]

    def list(self, config: Optional[RunnableConfig], **kwargs: Any):  # type: ignore[override]
        return super().list(_scoped(config), **kwargs)

    def put(self, config: RunnableConfig, *args: Any, **kwargs: Any):  # type: ignore[override]
        return super().put(_scoped(config), *args, **kwargs)  # type: ignore[arg-type]

    def put_writes(self, config: RunnableConfig, *args: Any, **kwargs: Any):  # type: ignore[override]
        return super().put_writes(_scoped(config), *args, **kwargs)  # type: ignore[arg-type]

    def delete_thread(self, thread_id: str) -> None:  # type: ignore[override]
        prefix = (tenancy.current_tenant_db() or "core") + "::"
        tid = thread_id if str(thread_id).startswith(prefix) else prefix + str(thread_id)
        return super().delete_thread(tid)
