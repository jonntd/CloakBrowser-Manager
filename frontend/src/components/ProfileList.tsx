import { Plus, Search, Monitor } from "lucide-react";
import { useState } from "react";
import type { Account } from "../lib/api";
import { StatusIndicator } from "./StatusIndicator";

interface ProfileListProps {
  profiles: Account[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export function ProfileList({ profiles, selectedId, onSelect, onNew }: ProfileListProps) {
  const [search, setSearch] = useState("");

  const filtered = profiles.filter((p) => {
    const q = search.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      (p.site ?? "").toLowerCase().includes(q)
    );
  });

  const runningCount = profiles.filter((p) => p.status === "running").length;

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 mb-3">
          <Monitor className="h-4 w-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight">CloakAccounts</h1>
        </div>
        {runningCount > 0 && (
          <div className="text-xs text-gray-500 mb-3">{runningCount} 个运行中</div>
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
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <div className="text-center text-gray-500 text-xs py-8">
            {profiles.length === 0 ? "还没有账号" : "无匹配结果"}
          </div>
        )}
        {filtered.map((account) => (
          <button
            key={account.id}
            onClick={() => onSelect(account.id)}
            className={`w-full text-left px-3 py-2.5 rounded-md mb-1 transition-colors ${
              selectedId === account.id
                ? "bg-surface-3 border border-border-hover"
                : "hover:bg-surface-2 border border-transparent"
            }`}
          >
            <div className="flex items-center gap-2">
              <StatusIndicator status={account.status} />
              <span className="text-sm font-medium truncate">{account.name}</span>
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
          </button>
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
