import { Plus, Search, Monitor, Play, Square, Loader2 } from "lucide-react";
import { useState } from "react";
import type { Account } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface ProfileListProps {
  profiles: Account[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onOpen: (id: string) => Promise<unknown>;
  onOpenMany: (ids: string[]) => Promise<unknown>;
  onStop: (id: string) => Promise<unknown>;
  onStopMany: (ids: string[]) => Promise<unknown>;
  onStopAll: () => Promise<unknown>;
}

export function ProfileList({ profiles, selectedId, onSelect, onNew, onOpen, onOpenMany, onStop, onStopMany, onStopAll }: ProfileListProps) {
  const [search, setSearch] = useState("");
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [stopAllLoading, setStopAllLoading] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [batchLoading, setBatchLoading] = useState(false);

  const toggleChecked = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleStopAll = async () => {
    setStopAllLoading(true);
    try {
      await onStopAll();
    } finally {
      setStopAllLoading(false);
    }
  };

  const handleBatchLaunch = async () => {
    // Only launch checked accounts that aren't already running.
    const ids = [...checked].filter(
      (id) => profiles.find((p) => p.id === id)?.status !== "running",
    );
    if (ids.length === 0) return;
    setBatchLoading(true);
    try {
      await onOpenMany(ids);
      setChecked(new Set());
    } finally {
      setBatchLoading(false);
    }
  };

  const handleBatchStop = async () => {
    // Only stop checked accounts that are currently running.
    const ids = [...checked].filter(
      (id) => profiles.find((p) => p.id === id)?.status === "running",
    );
    if (ids.length === 0) return;
    setBatchLoading(true);
    try {
      await onStopMany(ids);
      setChecked(new Set());
    } finally {
      setBatchLoading(false);
    }
  };

  const handleAction = async (id: string, action: "open" | "stop") => {
    setActionLoading((prev) => ({ ...prev, [id]: true }));
    try {
      if (action === "open") await onOpen(id);
      else await onStop(id);
    } catch {
      // error surfaced via useAccounts
    } finally {
      setActionLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const filtered = profiles.filter((p) => {
    const q = search.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      (p.site ?? "").toLowerCase().includes(q)
    );
  });

  const runningCount = profiles.filter((p) => p.status === "running").length;

  const allFilteredChecked = filtered.length > 0 && filtered.every((p) => checked.has(p.id));
  const toggleAll = () => {
    setChecked((prev) => {
      if (filtered.every((p) => prev.has(p.id))) {
        // all filtered are checked → clear those
        const next = new Set(prev);
        filtered.forEach((p) => next.delete(p.id));
        return next;
      }
      const next = new Set(prev);
      filtered.forEach((p) => next.add(p.id));
      return next;
    });
  };

  const checkedRunning = [...checked].filter(
    (id) => profiles.find((p) => p.id === id)?.status === "running",
  ).length;
  const checkedStopped = checked.size - checkedRunning;

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <Monitor className="h-4 w-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight">CloakAccounts</h1>
        </div>
        {runningCount > 0 && (
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-gray-500">{runningCount} 个运行中</span>
            <button
              onClick={handleStopAll}
              disabled={stopAllLoading}
              className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
              title="停止所有运行中的浏览器"
            >
              {stopAllLoading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Square className="h-3 w-3" />
              )}
              <span>全部停止</span>
            </button>
          </div>
        )}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            type="text"
            placeholder="搜索账号..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs"
          />
        </div>

        {filtered.length > 0 && (
          <div className="flex items-center justify-between gap-2 mt-3">
            <label className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={allFilteredChecked}
                onChange={toggleAll}
                className="rounded border-border bg-surface-2 cursor-pointer"
              />
              <span>{checked.size > 0 ? `已选 ${checked.size}` : "全选"}</span>
            </label>
            {checked.size > 0 && (
              <div className="flex items-center gap-1.5">
                {checkedRunning > 0 && (
                  <button
                    onClick={handleBatchStop}
                    disabled={batchLoading}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors disabled:opacity-60"
                    title="停止所有选中且运行中的账号"
                  >
                    <Square className="h-3.5 w-3.5" />
                    <span>停止</span>
                  </button>
                )}
                {checkedStopped > 0 && (
                  <button
                    onClick={handleBatchLaunch}
                    disabled={batchLoading}
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-60"
                    title="启动所有选中且未运行的账号"
                  >
                    {batchLoading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    <span>启动</span>
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <div className="text-center text-gray-500 text-xs py-8">
            {profiles.length === 0 ? "还没有账号" : "无匹配结果"}
          </div>
        )}
        {filtered.map((account) => (
          <div
            key={account.id}
            className={`group relative px-3 py-2.5 rounded-md mb-1 transition-colors cursor-pointer ${
              selectedId === account.id
                ? "bg-surface-3 border border-border-hover"
                : "hover:bg-surface-2 border border-transparent"
            }`}
            onClick={() => onSelect(account.id)}
          >
            <div className="flex items-center justify-between gap-1">
              <div className="flex items-center gap-2 min-w-0">
                <input
                  type="checkbox"
                  checked={checked.has(account.id)}
                  onChange={() => toggleChecked(account.id)}
                  onClick={(e) => e.stopPropagation()}
                  className="flex-shrink-0 rounded border-border bg-surface-2 cursor-pointer"
                  title="选择用于批量启动"
                />
                <StatusIndicator status={account.status} />
                <span className="text-sm font-medium truncate">{account.name}</span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleAction(account.id, account.status === "running" ? "stop" : "open");
                }}
                disabled={actionLoading[account.id]}
                className={`flex-shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors disabled:opacity-60 ${
                  account.status === "running"
                    ? "bg-red-500/15 text-red-400 hover:bg-red-500/25"
                    : "bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25"
                }`}
                title={account.status === "running" ? "停止浏览器" : "启动浏览器"}
              >
                {actionLoading[account.id] ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : account.status === "running" ? (
                  <Square className="h-3.5 w-3.5" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                <span>{account.status === "running" ? "停止" : "启动"}</span>
              </button>
            </div>
            <div className="flex items-center gap-2 mt-1 ml-4">
              {account.site && (
                <span className="text-xs text-gray-400 truncate max-w-[120px]">{account.site}</span>
              )}
              <span className="text-xs text-gray-500 capitalize">{account.platform}</span>
              {account.proxy && (
                <>
                  <span className="text-xs text-gray-600">·</span>
                  <span className="text-xs text-gray-500">代理</span>
                </>
              )}
            </div>
            {account.tags.length > 0 && (
              <div className="flex gap-1 mt-1.5 ml-4 flex-wrap">
                {account.tags.map((t) => (
                  <span
                    key={t.tag}
                    className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-4 text-gray-400"
                    style={t.color ? { backgroundColor: `${t.color}20`, color: t.color } : undefined}
                  >
                    {t.tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="p-3 border-t border-border">
        <button onClick={onNew} className="btn-secondary w-full flex items-center justify-center gap-1.5">
          <Plus className="h-3.5 w-3.5" />
          <span>新建账号</span>
        </button>
      </div>
    </div>
  );
}
