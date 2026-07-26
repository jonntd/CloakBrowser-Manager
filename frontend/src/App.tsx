import { useState, useCallback } from "react";
import { PanelLeftClose, PanelLeft, ExternalLink, X, Copy, Check } from "lucide-react";
import { useAccounts } from "./hooks/useAccounts";
import type { AccountCreateData } from "./lib/api";
import { ProfileList } from "./components/ProfileList";
import { ProfileForm } from "./components/ProfileForm";
import { StatusIndicator } from "./components/StatusIndicator";

type View = "empty" | "create" | "edit";

/** Copy text via a hidden textarea + execCommand — works in the Tauri webview
 *  without the clipboard plugin/permission. */
function copyText(text: string): boolean {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return true;
  } catch {
    return false;
  }
}

export default function App() {
  const { accounts, endpoints, loading, error, dismissError, create, update, remove, open, openMany, stop, stopMany, stopAll, clearData, clearAllCache } = useAccounts();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [copied, setCopied] = useState(false);

  const selected = accounts.find((a) => a.id === selectedId) ?? null;
  const selectedEndpoint = selected ? endpoints[selected.id] : undefined;

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
            onOpen={open}
            onOpenMany={openMany}
            onStop={stop}
            onStopMany={stopMany}
            onStopAll={stopAll}
            onClearAllCache={clearAllCache}
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
          {selected && selectedEndpoint && (
            <button
              onClick={() => {
                if (copyText(selectedEndpoint.cdp_url)) {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              }}
              className="flex items-center gap-1.5 text-xs font-mono text-gray-400 hover:text-gray-200 bg-surface-2 hover:bg-surface-3 rounded px-2 py-1"
              title="复制 CDP 地址（供 Claude / Playwright 连接控制）"
            >
              <span>CDP {selectedEndpoint.cdp_url.replace("http://", "")}</span>
              {copied ? (
                <Check className="h-3 w-3 text-emerald-400" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
            </button>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm flex items-start justify-between gap-3">
            <span className="whitespace-pre-line">{error}</span>
            <button
              onClick={dismissError}
              className="flex-shrink-0 text-red-400/70 hover:text-red-300"
              title="关闭"
            >
              <X className="h-4 w-4" />
            </button>
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
                onRandomizeFingerprint={() => update(selected.id, {
                  fingerprint_seed: Math.floor(Math.random() * 90000) + 10000,
                })}
                onClearData={() => clearData(selected.id)}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
