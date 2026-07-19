import { useState, useCallback } from "react";
import { PanelLeftClose, PanelLeft, ExternalLink } from "lucide-react";
import { useAccounts } from "./hooks/useAccounts";
import type { AccountCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";

type View = "empty" | "create" | "edit";

export default function App() {
  const { accounts, loading, error, create, update, remove, open, stop } = useAccounts();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const selected = accounts.find((a) => a.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    setView("edit");
  }, []);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(
    async (data: AccountCreateData) => {
      const account = await create(data);
      if (account) {
        setSelectedId(account.id);
        setView("edit");
      }
    },
    [create],
  );

  const handleUpdate = useCallback(
    async (data: AccountCreateData) => {
      if (!selectedId) return;
      await update(selectedId, data);
    },
    [selectedId, update],
  );

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    await open(selectedId);
  }, [selectedId, open]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
  }, [selectedId, stop]);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface-0">
        <div className="text-gray-500 text-sm">加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex bg-surface-0 text-gray-100">
      {/* Sidebar */}
      {sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={accounts}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "隐藏侧边栏" : "显示侧边栏"}
            >
              {sidebarOpen ? (
                <PanelLeftClose className="h-4 w-4" />
              ) : (
                <PanelLeft className="h-4 w-4" />
              )}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
                {selected.site && (
                  <span className="text-xs text-gray-500">{selected.site}</span>
                )}
                <span className="text-xs text-gray-500 capitalize">{selected.platform}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {view === "empty" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center max-w-sm px-6">
                <p className="text-gray-300 text-sm font-medium mb-2">本地账号浏览器管理器</p>
                <p className="text-gray-500 text-sm">
                  选择左侧账号，或新建一个。每个账号拥有独立指纹、代理与 cookie，互不共用。
                </p>
                <button onClick={handleNew} className="btn-primary mt-4">
                  新建账号
                </button>
              </div>
            </div>
          )}

          {view === "create" && (
            <ProfileForm
              profile={null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
            />
          )}

          {view === "edit" && selected && (
            <>
              {selected.status === "running" && (
                <div className="mx-6 mt-4 px-4 py-3 rounded-md bg-emerald-600/10 border border-emerald-600/30 text-emerald-300 text-sm flex items-center gap-2">
                  <ExternalLink className="h-4 w-4 flex-shrink-0" />
                  <span>
                    浏览器窗口已在桌面打开（独立进程）。关闭桌面窗口后状态会自动变为已停止。
                  </span>
                </div>
              )}
              <ProfileForm
                profile={selected}
                onSave={handleUpdate}
                onDelete={handleDelete}
                onCancel={() => {
                  setSelectedId(null);
                  setView("empty");
                }}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
