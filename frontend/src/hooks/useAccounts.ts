import { useCallback, useEffect, useState } from "react";
import { api, type Account, type AccountCreateData } from "../lib/api";

export function useAccounts() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listAccounts();
      setAccounts(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取账号列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  const create = useCallback(
    async (data: AccountCreateData): Promise<Account | undefined> => {
      try {
        const account = await api.createAccount(data);
        setAccounts((prev) => [account, ...prev]);
        return account;
      } catch (err) {
        setError(err instanceof Error ? err.message : "创建账号失败");
      }
    },
    [],
  );

  const update = useCallback(
    async (id: string, data: Partial<AccountCreateData>) => {
      try {
        const account = await api.updateAccount(id, data);
        setAccounts((prev) => prev.map((a) => (a.id === id ? account : a)));
        return account;
      } catch (err) {
        setError(err instanceof Error ? err.message : "更新账号失败");
      }
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    try {
      await api.removeAccount(id);
      setAccounts((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除账号失败");
    }
  }, []);

  const open = useCallback(
    async (id: string) => {
      try {
        const result = await api.openAccount(id);
        await refresh();
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : "启动浏览器失败");
      }
    },
    [refresh],
  );

  const stop = useCallback(
    async (id: string) => {
      try {
        await api.stopAccount(id);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "停止浏览器失败");
      }
    },
    [refresh],
  );

  return { accounts, loading, error, refresh, create, update, remove, open, stop };
}

/** @deprecated use useAccounts */
